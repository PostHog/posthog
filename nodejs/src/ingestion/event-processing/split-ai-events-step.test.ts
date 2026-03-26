import { ISOTimestamp, ProcessedEvent, ProjectId } from '../../types'
import { AI_EVENTS_OUTPUT, EVENTS_OUTPUT } from '../analytics/outputs'
import { isOkResult } from '../pipelines/results'
import { SplitAiEventsStepConfig, createSplitAiEventsStep, parseSplitAiEventsConfig } from './split-ai-events-step'

function createProcessedEvent(
    properties: Record<string, unknown> = {},
    overrides: Partial<ProcessedEvent> = {}
): ProcessedEvent {
    return {
        uuid: 'event-uuid-123',
        event: '$ai_generation',
        team_id: 1,
        project_id: 1 as ProjectId,
        distinct_id: 'user-1',
        timestamp: '2023-01-01T00:00:00.000Z' as ISOTimestamp,
        created_at: null,
        captured_at: null,
        elements_chain: '',
        person_id: 'person-uuid',
        person_mode: 'full',
        properties,
        person_properties: {},
        person_created_at: null,
        ...overrides,
    }
}

const ENABLED_FOR_ALL: SplitAiEventsStepConfig = { enabled: true, enabledTeams: '*' }

describe('split-ai-events-step', () => {
    describe('parseSplitAiEventsConfig', () => {
        it.each([
            { enabled: true, teams: '*', expected: { enabled: true, enabledTeams: '*' } },
            { enabled: false, teams: '*', expected: { enabled: false, enabledTeams: '*' } },
            { enabled: true, teams: '1,2,3', expected: { enabled: true, enabledTeams: new Set([1, 2, 3]) } },
            { enabled: true, teams: ' 1 , 2 ', expected: { enabled: true, enabledTeams: new Set([1, 2]) } },
            { enabled: true, teams: '', expected: { enabled: true, enabledTeams: new Set() } },
            { enabled: true, teams: 'abc,1', expected: { enabled: true, enabledTeams: new Set([1]) } },
        ])('should parse enabled=$enabled teams=$teams', ({ enabled, teams, expected }) => {
            expect(parseSplitAiEventsConfig(enabled, teams)).toEqual(expected)
        })
    })

    describe('feature flag behavior', () => {
        it('should pass through unchanged when disabled', async () => {
            const step = createSplitAiEventsStep({ enabled: false, enabledTeams: '*' })
            const event = createProcessedEvent({ $ai_input: 'large input', $ai_model: 'gpt-4' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
            expect(result.value.eventsToEmit[0].event.properties).toHaveProperty('$ai_input')
        })

        it('should pass through unchanged when team is not in the enabled set', async () => {
            const step = createSplitAiEventsStep({ enabled: true, enabledTeams: new Set([99, 100]) })
            const event = createProcessedEvent({ $ai_input: 'large input' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
        })

        it('should split when team is in the enabled set', async () => {
            const step = createSplitAiEventsStep({ enabled: true, enabledTeams: new Set([1, 2]) })
            const event = createProcessedEvent({ $ai_input: 'large input', $ai_model: 'gpt-4' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(2)
        })

        it('should split when enabled for all teams', async () => {
            const step = createSplitAiEventsStep({ enabled: true, enabledTeams: '*' })
            const event = createProcessedEvent({ $ai_input: 'large input', $ai_model: 'gpt-4' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 999 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(2)
        })
    })

    describe('splitting behavior', () => {
        const step = createSplitAiEventsStep(ENABLED_FOR_ALL)

        it('should split an event with large AI properties into stripped + full', async () => {
            const event = createProcessedEvent({
                $ai_input: 'large input',
                $ai_output: 'large output',
                $ai_model: 'gpt-4',
                $browser: 'Chrome',
            })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)

            const [mainEntry, aiEntry] = eventsToEmit
            expect(mainEntry.output).toBe(EVENTS_OUTPUT)
            expect(aiEntry.output).toBe(AI_EVENTS_OUTPUT)

            expect(mainEntry.event.properties).toEqual({ $ai_model: 'gpt-4', $browser: 'Chrome' })
            expect(aiEntry.event.properties).toEqual({
                $ai_input: 'large input',
                $ai_output: 'large output',
                $ai_model: 'gpt-4',
                $browser: 'Chrome',
            })
        })

        it.each(['$ai_input', '$ai_output', '$ai_output_choices', '$ai_input_state', '$ai_output_state', '$ai_tools'])(
            'should strip %s from the main output event',
            async (property) => {
                const event = createProcessedEvent({ [property]: 'large value', $ai_model: 'gpt-4' })

                const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
                expect(isOkResult(result)).toBe(true)
                if (!isOkResult(result)) {
                    return
                }

                const { eventsToEmit } = result.value
                expect(eventsToEmit).toHaveLength(2)

                expect(eventsToEmit[0].event.properties).not.toHaveProperty(property)
                expect(eventsToEmit[1].event.properties).toHaveProperty(property, 'large value')
            }
        )

        it('should pass through event without large AI properties', async () => {
            const event = createProcessedEvent({ $ai_model: 'gpt-4', $browser: 'Chrome' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(1)
            expect(eventsToEmit[0].event).toBe(event)
            expect(eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
        })

        it('should handle multiple events independently', async () => {
            const aiEvent = createProcessedEvent({ $ai_input: 'large', $ai_model: 'gpt-4' }, { uuid: 'ai-1' })
            const regularEvent = createProcessedEvent({ $browser: 'Chrome' }, { uuid: 'regular-1', event: '$pageview' })

            const result = await step({
                eventsToEmit: [
                    { event: aiEvent, output: EVENTS_OUTPUT },
                    { event: regularEvent, output: EVENTS_OUTPUT },
                ],
                teamId: 1,
            })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(3)

            expect(eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
            expect(eventsToEmit[0].event.properties).not.toHaveProperty('$ai_input')
            expect(eventsToEmit[1].output).toBe(AI_EVENTS_OUTPUT)
            expect(eventsToEmit[1].event.properties).toHaveProperty('$ai_input', 'large')
            expect(eventsToEmit[2].event).toBe(regularEvent)
            expect(eventsToEmit[2].output).toBe(EVENTS_OUTPUT)
        })

        it('should handle empty properties', async () => {
            const event = createProcessedEvent({})

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
            expect(result.value.eventsToEmit[0].event).toBe(event)
        })

        it('should handle undefined properties', async () => {
            const event = createProcessedEvent()
            event.properties = undefined as any

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
            expect(result.value.eventsToEmit[0].event).toBe(event)
        })

        it('should handle empty input', async () => {
            const result = await step({ eventsToEmit: [], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(0)
        })

        it('should copy for main output and keep original for AI output', async () => {
            const event = createProcessedEvent({ $ai_input: 'large input', $ai_model: 'gpt-4' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)

            // Main output entry is a copy with stripped properties
            expect(eventsToEmit[0].event).not.toBe(event)
            expect(eventsToEmit[0].event.properties).not.toHaveProperty('$ai_input')

            // AI output entry keeps the original event object
            expect(eventsToEmit[1].event).toBe(event)
        })
    })
})
