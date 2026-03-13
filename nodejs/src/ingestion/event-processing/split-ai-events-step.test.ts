import { ISOTimestamp, ProcessedEvent, ProjectId } from '../../types'
import { isOkResult } from '../pipelines/results'
import { AI_EVENTS_OUTPUT, EVENTS_OUTPUT } from './ingestion-outputs'
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

const ENABLED_FOR_ALL: SplitAiEventsStepConfig = { enabled: true, enabledTeams: '*', stripHeavyProperties: true }
const ENABLED_NO_STRIP: SplitAiEventsStepConfig = { enabled: true, enabledTeams: '*', stripHeavyProperties: false }

describe('split-ai-events-step', () => {
    describe('parseSplitAiEventsConfig', () => {
        it.each([
            {
                enabled: true,
                teams: '*',
                strip: false,
                expected: { enabled: true, enabledTeams: '*', stripHeavyProperties: false },
            },
            {
                enabled: false,
                teams: '*',
                strip: false,
                expected: { enabled: false, enabledTeams: '*', stripHeavyProperties: false },
            },
            {
                enabled: true,
                teams: '1,2,3',
                strip: true,
                expected: { enabled: true, enabledTeams: new Set([1, 2, 3]), stripHeavyProperties: true },
            },
            {
                enabled: true,
                teams: ' 1 , 2 ',
                strip: false,
                expected: { enabled: true, enabledTeams: new Set([1, 2]), stripHeavyProperties: false },
            },
            {
                enabled: true,
                teams: '',
                strip: false,
                expected: { enabled: true, enabledTeams: new Set(), stripHeavyProperties: false },
            },
            {
                enabled: true,
                teams: 'abc,1',
                strip: false,
                expected: { enabled: true, enabledTeams: new Set([1]), stripHeavyProperties: false },
            },
        ])('should parse enabled=$enabled teams=$teams strip=$strip', ({ enabled, teams, strip, expected }) => {
            expect(parseSplitAiEventsConfig(enabled, teams, strip)).toEqual(expected)
        })
    })

    describe('feature flag behavior', () => {
        it('should pass through unchanged when disabled', async () => {
            const step = createSplitAiEventsStep({
                enabled: false,
                enabledTeams: '*',
                stripHeavyProperties: false,
            })
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
            const step = createSplitAiEventsStep({
                enabled: true,
                enabledTeams: new Set([99, 100]),
                stripHeavyProperties: false,
            })
            const event = createProcessedEvent({ $ai_input: 'large input' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
        })

        it('should split when team is in the enabled set', async () => {
            const step = createSplitAiEventsStep({
                enabled: true,
                enabledTeams: new Set([1, 2]),
                stripHeavyProperties: true,
            })
            const event = createProcessedEvent({ $ai_input: 'large input', $ai_model: 'gpt-4' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(2)
        })

        it('should split when enabled for all teams', async () => {
            const step = createSplitAiEventsStep({
                enabled: true,
                enabledTeams: '*',
                stripHeavyProperties: true,
            })
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

        it('should send AI event without large properties to both outputs', async () => {
            const event = createProcessedEvent({ $ai_model: 'gpt-4', $browser: 'Chrome' }, { event: '$ai_metric' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)
            expect(eventsToEmit[0].event).toBe(event)
            expect(eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
            expect(eventsToEmit[1].event).toBe(event)
            expect(eventsToEmit[1].output).toBe(AI_EVENTS_OUTPUT)
        })

        it.each([
            '$ai_metric',
            '$ai_feedback',
            '$ai_evaluation',
            '$ai_generation',
            '$ai_span',
            '$ai_trace',
            '$ai_embedding',
        ])('should send %s without large properties to both outputs', async (eventName) => {
            const event = createProcessedEvent({ $ai_model: 'gpt-4' }, { event: eventName })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)
            expect(eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
            expect(eventsToEmit[1].output).toBe(AI_EVENTS_OUTPUT)
        })

        it('should pass through non-AI event without large AI properties', async () => {
            const event = createProcessedEvent({ $browser: 'Chrome' }, { event: '$pageview' })

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

        it('should handle AI event with empty properties', async () => {
            const event = createProcessedEvent({})

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            // $ai_generation is an AI event, so it goes to both outputs
            expect(result.value.eventsToEmit).toHaveLength(2)
            expect(result.value.eventsToEmit[0].event).toBe(event)
            expect(result.value.eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
            expect(result.value.eventsToEmit[1].event).toBe(event)
            expect(result.value.eventsToEmit[1].output).toBe(AI_EVENTS_OUTPUT)
        })

        it('should handle non-AI event with empty properties', async () => {
            const event = createProcessedEvent({}, { event: '$pageview' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
            expect(result.value.eventsToEmit[0].event).toBe(event)
        })

        it('should handle undefined properties on non-AI event', async () => {
            const event = createProcessedEvent({}, { event: '$pageview' })
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

    describe('non-stripping mode (stripHeavyProperties=false)', () => {
        const step = createSplitAiEventsStep(ENABLED_NO_STRIP)

        it('should send AI event with heavy properties unchanged to both outputs', async () => {
            const event = createProcessedEvent({
                $ai_input: 'large input',
                $ai_output: 'large output',
                $ai_model: 'gpt-4',
            })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)

            // Both outputs get the same unchanged event
            expect(eventsToEmit[0].event).toBe(event)
            expect(eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
            expect(eventsToEmit[0].event.properties).toHaveProperty('$ai_input', 'large input')

            expect(eventsToEmit[1].event).toBe(event)
            expect(eventsToEmit[1].output).toBe(AI_EVENTS_OUTPUT)
            expect(eventsToEmit[1].event.properties).toHaveProperty('$ai_input', 'large input')
        })

        it('should still pass through non-AI events unchanged', async () => {
            const event = createProcessedEvent({ $browser: 'Chrome' }, { event: '$pageview' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
            expect(result.value.eventsToEmit[0].event).toBe(event)
        })

        it('should send AI event without heavy properties to both outputs', async () => {
            const event = createProcessedEvent({ $ai_model: 'gpt-4' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)
            expect(eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
            expect(eventsToEmit[1].output).toBe(AI_EVENTS_OUTPUT)
        })
    })
})
