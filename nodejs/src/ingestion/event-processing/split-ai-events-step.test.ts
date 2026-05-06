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

const ENABLED_FOR_ALL: SplitAiEventsStepConfig = {
    enabled: true,
    enabledTeams: '*',
    enabledPercentage: 0,
    stripHeavyTeams: '*',
}
const ENABLED_NO_STRIP: SplitAiEventsStepConfig = {
    enabled: true,
    enabledTeams: '*',
    enabledPercentage: 0,
    stripHeavyTeams: [],
}

describe('split-ai-events-step', () => {
    describe('parseSplitAiEventsConfig', () => {
        it.each([
            {
                enabled: true,
                teams: '*',
                stripTeams: '',
                expected: { enabled: true, enabledTeams: '*', enabledPercentage: 0, stripHeavyTeams: [] },
            },
            {
                enabled: false,
                teams: '*',
                stripTeams: '',
                expected: { enabled: false, enabledTeams: '*', enabledPercentage: 0, stripHeavyTeams: [] },
            },
            {
                enabled: true,
                teams: '1,2,3',
                stripTeams: '*',
                expected: { enabled: true, enabledTeams: [1, 2, 3], enabledPercentage: 0, stripHeavyTeams: '*' },
            },
            {
                enabled: true,
                teams: ' 1 , 2 ',
                stripTeams: '2',
                expected: { enabled: true, enabledTeams: [1, 2], enabledPercentage: 0, stripHeavyTeams: [2] },
            },
            {
                enabled: true,
                teams: '',
                stripTeams: '',
                expected: { enabled: true, enabledTeams: [], enabledPercentage: 0, stripHeavyTeams: [] },
            },
            {
                enabled: true,
                teams: 'abc,1',
                stripTeams: 'abc,2',
                expected: { enabled: true, enabledTeams: [1], enabledPercentage: 0, stripHeavyTeams: [2] },
            },
        ])(
            'should parse enabled=$enabled teams=$teams stripTeams=$stripTeams',
            ({ enabled, teams, stripTeams, expected }) => {
                expect(parseSplitAiEventsConfig(enabled, teams, stripTeams)).toEqual(expected)
            }
        )

        it.each([
            { input: 25, expected: 25 },
            { input: 0, expected: 0 },
            { input: 100, expected: 100 },
            { input: 150, expected: 100 },
            { input: -5, expected: 0 },
            { input: NaN, expected: 0 },
            { input: Infinity, expected: 100 },
        ])('should clamp percentage $input -> $expected', ({ input, expected }) => {
            expect(parseSplitAiEventsConfig(true, '', '', input).enabledPercentage).toBe(expected)
        })
    })

    describe('feature flag behavior', () => {
        it('should pass through unchanged when disabled', async () => {
            const step = createSplitAiEventsStep({
                enabled: false,
                enabledTeams: '*',
                enabledPercentage: 0,
                stripHeavyTeams: '*',
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

        it('should pass through unchanged when team is not in the enabled list', async () => {
            const step = createSplitAiEventsStep({
                enabled: true,
                enabledTeams: [99, 100],
                enabledPercentage: 0,
                stripHeavyTeams: '*',
            })
            const event = createProcessedEvent({ $ai_input: 'large input' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
        })

        it('should split when team is in the enabled list', async () => {
            const step = createSplitAiEventsStep({
                enabled: true,
                enabledTeams: [1, 2],
                enabledPercentage: 0,
                stripHeavyTeams: '*',
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
                enabledPercentage: 0,
                stripHeavyTeams: '*',
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

        it.each(['$ai_feedback', '$ai_evaluation', '$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding'])(
            'should send %s without large properties to both outputs',
            async (eventName) => {
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
            }
        )

        it.each([
            { props: { $browser: 'Chrome' }, desc: 'without large AI properties' },
            { props: { $browser: 'Chrome', $ai_input: 'large input' }, desc: 'with large AI properties' },
        ])('should pass through non-AI event $desc to single output', async ({ props }) => {
            const event = createProcessedEvent(props, { event: '$pageview' })

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

    describe('non-stripping mode (stripHeavyTeams empty array)', () => {
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

    describe('per-team strip allowlist', () => {
        const step = createSplitAiEventsStep({
            enabled: true,
            enabledTeams: '*',
            enabledPercentage: 0,
            stripHeavyTeams: [2],
        })

        it('should strip heavy props for a team in stripHeavyTeams', async () => {
            const event = createProcessedEvent({ $ai_input: 'large input', $ai_model: 'gpt-4' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 2 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)
            expect(eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
            expect(eventsToEmit[0].event.properties).not.toHaveProperty('$ai_input')
            expect(eventsToEmit[1].output).toBe(AI_EVENTS_OUTPUT)
            expect(eventsToEmit[1].event.properties).toHaveProperty('$ai_input', 'large input')
        })

        it('should double-write unchanged for teams not in stripHeavyTeams', async () => {
            const event = createProcessedEvent({ $ai_input: 'large input', $ai_model: 'gpt-4' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)
            expect(eventsToEmit[0].event).toBe(event)
            expect(eventsToEmit[0].event.properties).toHaveProperty('$ai_input', 'large input')
            expect(eventsToEmit[1].event).toBe(event)
            expect(eventsToEmit[1].event.properties).toHaveProperty('$ai_input', 'large input')
        })
    })

    describe('percentage rollout', () => {
        async function runForTeam(config: SplitAiEventsStepConfig, teamId: number): Promise<number> {
            const step = createSplitAiEventsStep(config)
            const event = createProcessedEvent({ $ai_input: 'x', $ai_model: 'gpt-4' })
            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId })
            if (!isOkResult(result)) {
                throw new Error('expected ok result')
            }
            return result.value.eventsToEmit.length
        }

        it('routes no team when percentage is 0 and team list is empty', async () => {
            const config: SplitAiEventsStepConfig = {
                enabled: true,
                enabledTeams: [],
                enabledPercentage: 0,
                stripHeavyTeams: [],
            }
            for (const teamId of [1, 2, 3, 99, 1234]) {
                expect(await runForTeam(config, teamId)).toBe(1)
            }
        })

        it('routes every team when percentage is 100', async () => {
            const config: SplitAiEventsStepConfig = {
                enabled: true,
                enabledTeams: [],
                enabledPercentage: 100,
                stripHeavyTeams: [],
            }
            for (const teamId of [1, 2, 3, 99, 1234]) {
                expect(await runForTeam(config, teamId)).toBe(2)
            }
        })

        it('rollout is monotonic — every team in at X% stays in at any Y% > X%', async () => {
            const teamIds = Array.from({ length: 1000 }, (_, i) => i + 1)
            const inAt: Record<number, Set<number>> = {}
            for (const pct of [10, 25, 50, 75, 90, 100]) {
                const config: SplitAiEventsStepConfig = {
                    enabled: true,
                    enabledTeams: [],
                    enabledPercentage: pct,
                    stripHeavyTeams: [],
                }
                inAt[pct] = new Set()
                for (const teamId of teamIds) {
                    if ((await runForTeam(config, teamId)) === 2) {
                        inAt[pct].add(teamId)
                    }
                }
            }
            for (const [lo, hi] of [
                [10, 25],
                [25, 50],
                [50, 75],
                [75, 90],
                [90, 100],
            ]) {
                for (const teamId of inAt[lo]) {
                    expect(inAt[hi].has(teamId)).toBe(true)
                }
            }
        })

        it('rollout bucket distribution stays close to the configured percentage', async () => {
            const teamIds = Array.from({ length: 10_000 }, (_, i) => i + 1)
            const config: SplitAiEventsStepConfig = {
                enabled: true,
                enabledTeams: [],
                enabledPercentage: 25,
                stripHeavyTeams: [],
            }
            let routed = 0
            for (const teamId of teamIds) {
                if ((await runForTeam(config, teamId)) === 2) {
                    routed++
                }
            }
            const ratio = routed / teamIds.length
            expect(ratio).toBeGreaterThan(0.22)
            expect(ratio).toBeLessThan(0.28)
        })

        it('union: explicit team is always routed, even when its bucket falls outside the percentage', async () => {
            // Team 2's bucket is 26 — at percentage 10 it would be excluded by hash alone.
            const config: SplitAiEventsStepConfig = {
                enabled: true,
                enabledTeams: [2],
                enabledPercentage: 10,
                stripHeavyTeams: [],
            }
            expect(await runForTeam(config, 2)).toBe(2)
        })

        it('union: percentage routes additional teams beyond the explicit list', async () => {
            const config: SplitAiEventsStepConfig = {
                enabled: true,
                enabledTeams: [2],
                enabledPercentage: 50,
                stripHeavyTeams: [],
            }
            // teamId 5 → bucket 17 (under 50%); not in the explicit list
            expect(await runForTeam(config, 5)).toBe(2)
            // teamId 2 → in the explicit list
            expect(await runForTeam(config, 2)).toBe(2)
            // teamId 3 → bucket 87 (above 50%); not in the explicit list
            expect(await runForTeam(config, 3)).toBe(1)
        })

        it("'*' routes everything regardless of percentage", async () => {
            const config: SplitAiEventsStepConfig = {
                enabled: true,
                enabledTeams: '*',
                enabledPercentage: 0,
                stripHeavyTeams: [],
            }
            expect(await runForTeam(config, 1)).toBe(2)
            expect(await runForTeam(config, 999_999)).toBe(2)
        })

        it('bucketing stays stable for team ids past the f64-precision threshold (~3.4M)', async () => {
            // Without Math.imul, `teamId * 2654435761` loses precision past 2^53, shifting
            // the bucket by ±1 for teamIds ≳ 3.4M. teamId 3_393_265 lands in bucket 77
            // under the corrected implementation; the naive multiplication would produce 76.
            const noRollout: SplitAiEventsStepConfig = {
                enabled: true,
                enabledTeams: [],
                enabledPercentage: 77,
                stripHeavyTeams: [],
            }
            const fullRollout: SplitAiEventsStepConfig = {
                enabled: true,
                enabledTeams: [],
                enabledPercentage: 78,
                stripHeavyTeams: [],
            }
            // bucket 77, threshold 77 → not routed; threshold 78 → routed.
            expect(await runForTeam(noRollout, 3_393_265)).toBe(1)
            expect(await runForTeam(fullRollout, 3_393_265)).toBe(2)
            // High teamIds still respect 0% and 100% boundaries.
            for (const teamId of [10_000_000, 50_000_000, 99_999_999]) {
                expect(await runForTeam({ ...noRollout, enabledPercentage: 0 }, teamId)).toBe(1)
                expect(await runForTeam({ ...noRollout, enabledPercentage: 100 }, teamId)).toBe(2)
            }
        })
    })
})
