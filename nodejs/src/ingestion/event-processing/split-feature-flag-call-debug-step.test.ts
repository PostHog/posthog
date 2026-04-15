import { ISOTimestamp, ProcessedEvent, ProjectId } from '../../types'
import { EVENTS_OUTPUT, FEATURE_FLAG_CALL_DEBUG_OUTPUT } from '../analytics/outputs'
import { isOkResult } from '../pipelines/results'
import {
    SplitFeatureFlagCallDebugConfig,
    createSplitFeatureFlagCallDebugStep,
    parseSplitFeatureFlagCallDebugConfig,
} from './split-feature-flag-call-debug-step'

function createProcessedEvent(
    properties: Record<string, unknown> = {},
    overrides: Partial<ProcessedEvent> = {}
): ProcessedEvent {
    return {
        uuid: 'event-uuid-123',
        event: '$feature_flag_called',
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

const ENABLED_FOR_ALL: SplitFeatureFlagCallDebugConfig = {
    enabled: true,
    enabledTeams: '*',
    stripProperties: true,
}
const ENABLED_NO_STRIP: SplitFeatureFlagCallDebugConfig = {
    enabled: true,
    enabledTeams: '*',
    stripProperties: false,
}

describe('split-feature-flag-call-debug-step', () => {
    describe('parseSplitFeatureFlagCallDebugConfig', () => {
        it.each([
            {
                enabled: true,
                teams: '*',
                strip: false,
                expected: { enabled: true, enabledTeams: '*', stripProperties: false },
            },
            {
                enabled: false,
                teams: '*',
                strip: false,
                expected: { enabled: false, enabledTeams: '*', stripProperties: false },
            },
            {
                enabled: true,
                teams: '1,2,3',
                strip: true,
                expected: { enabled: true, enabledTeams: new Set([1, 2, 3]), stripProperties: true },
            },
            {
                enabled: true,
                teams: ' 1 , 2 ',
                strip: false,
                expected: { enabled: true, enabledTeams: new Set([1, 2]), stripProperties: false },
            },
            {
                enabled: true,
                teams: '',
                strip: false,
                expected: { enabled: true, enabledTeams: new Set(), stripProperties: false },
            },
            {
                enabled: true,
                teams: 'abc,1',
                strip: false,
                expected: { enabled: true, enabledTeams: new Set([1]), stripProperties: false },
            },
        ])('should parse enabled=$enabled teams=$teams strip=$strip', ({ enabled, teams, strip, expected }) => {
            expect(parseSplitFeatureFlagCallDebugConfig(enabled, teams, strip)).toEqual(expected)
        })
    })

    describe('feature flag behavior', () => {
        it('should pass through unchanged when disabled', async () => {
            const step = createSplitFeatureFlagCallDebugStep({
                enabled: false,
                enabledTeams: '*',
                stripProperties: false,
            })
            const event = createProcessedEvent({
                $feature_flag: 'my-flag',
                $feature_flag_response: true,
                $browser: 'Chrome',
            })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
            expect(result.value.eventsToEmit[0].event.properties).toHaveProperty('$browser')
        })

        it('should pass through unchanged when team is not in the enabled set', async () => {
            const step = createSplitFeatureFlagCallDebugStep({
                enabled: true,
                enabledTeams: new Set([99, 100]),
                stripProperties: true,
            })
            const event = createProcessedEvent({ $feature_flag: 'my-flag', $browser: 'Chrome' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
        })

        it('should split when team is in the enabled set', async () => {
            const step = createSplitFeatureFlagCallDebugStep({
                enabled: true,
                enabledTeams: new Set([1, 2]),
                stripProperties: true,
            })
            const event = createProcessedEvent({ $feature_flag: 'my-flag', $browser: 'Chrome' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(2)
        })

        it('should split when enabled for all teams', async () => {
            const step = createSplitFeatureFlagCallDebugStep(ENABLED_FOR_ALL)
            const event = createProcessedEvent({ $feature_flag: 'my-flag', $browser: 'Chrome' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 999 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(2)
        })
    })

    describe('splitting behavior', () => {
        const step = createSplitFeatureFlagCallDebugStep(ENABLED_FOR_ALL)

        it('should strip non-core properties from main output and keep full in debug output', async () => {
            const event = createProcessedEvent({
                $feature_flag: 'my-flag',
                $feature_flag_response: 'variant-a',
                $feature_flag_payload: '{"key":"value"}',
                $browser: 'Chrome',
                $os: 'Mac OS X',
                $current_url: 'https://example.com',
                $active_feature_flags: ['flag-1', 'flag-2'],
            })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)

            const [mainEntry, debugEntry] = eventsToEmit
            expect(mainEntry.output).toBe(EVENTS_OUTPUT)
            expect(debugEntry.output).toBe(FEATURE_FLAG_CALL_DEBUG_OUTPUT)

            // Main output keeps only core properties
            expect(mainEntry.event.properties).toEqual({
                $feature_flag: 'my-flag',
                $feature_flag_response: 'variant-a',
                $feature_flag_payload: '{"key":"value"}',
            })

            // Debug output has all original properties
            expect(debugEntry.event.properties).toEqual({
                $feature_flag: 'my-flag',
                $feature_flag_response: 'variant-a',
                $feature_flag_payload: '{"key":"value"}',
                $browser: 'Chrome',
                $os: 'Mac OS X',
                $current_url: 'https://example.com',
                $active_feature_flags: ['flag-1', 'flag-2'],
            })
        })

        it.each(['$browser', '$os', '$current_url', '$referrer', '$session_id', '$active_feature_flags'])(
            'should strip %s from the main output event',
            async (property) => {
                const event = createProcessedEvent({
                    $feature_flag: 'my-flag',
                    [property]: 'some value',
                })

                const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
                expect(isOkResult(result)).toBe(true)
                if (!isOkResult(result)) {
                    return
                }

                const { eventsToEmit } = result.value
                expect(eventsToEmit).toHaveLength(2)

                expect(eventsToEmit[0].event.properties).not.toHaveProperty(property)
                expect(eventsToEmit[1].event.properties).toHaveProperty(property, 'some value')
            }
        )

        it('should pass through non-$feature_flag_called event unchanged', async () => {
            const event = createProcessedEvent({ $feature_flag: 'my-flag', $browser: 'Chrome' }, { event: '$pageview' })

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
            const ffEvent = createProcessedEvent({ $feature_flag: 'my-flag', $browser: 'Chrome' }, { uuid: 'ff-1' })
            const regularEvent = createProcessedEvent({ $browser: 'Chrome' }, { uuid: 'regular-1', event: '$pageview' })

            const result = await step({
                eventsToEmit: [
                    { event: ffEvent, output: EVENTS_OUTPUT },
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
            expect(eventsToEmit[0].event.properties).not.toHaveProperty('$browser')
            expect(eventsToEmit[1].output).toBe(FEATURE_FLAG_CALL_DEBUG_OUTPUT)
            expect(eventsToEmit[1].event.properties).toHaveProperty('$browser', 'Chrome')
            expect(eventsToEmit[2].event).toBe(regularEvent)
            expect(eventsToEmit[2].output).toBe(EVENTS_OUTPUT)
        })

        it('should handle event with empty properties', async () => {
            const event = createProcessedEvent({})

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)
            expect(eventsToEmit[0].event.properties).toEqual({})
            expect(eventsToEmit[0].output).toBe(EVENTS_OUTPUT)
            expect(eventsToEmit[1].event.properties).toEqual({})
            expect(eventsToEmit[1].output).toBe(FEATURE_FLAG_CALL_DEBUG_OUTPUT)
        })

        it('should handle event with only core properties (nothing to strip)', async () => {
            const event = createProcessedEvent({
                $feature_flag: 'my-flag',
                $feature_flag_response: true,
                $feature_flag_payload: 'payload',
            })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)
            expect(eventsToEmit[0].event.properties).toEqual({
                $feature_flag: 'my-flag',
                $feature_flag_response: true,
                $feature_flag_payload: 'payload',
            })
            expect(eventsToEmit[1].event.properties).toEqual({
                $feature_flag: 'my-flag',
                $feature_flag_response: true,
                $feature_flag_payload: 'payload',
            })
        })

        it('should handle empty input', async () => {
            const result = await step({ eventsToEmit: [], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(0)
        })

        it('should create a copy for main output and keep original for debug output', async () => {
            const event = createProcessedEvent({
                $feature_flag: 'my-flag',
                $browser: 'Chrome',
            })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            const { eventsToEmit } = result.value
            expect(eventsToEmit).toHaveLength(2)

            // Main output entry is a copy with stripped properties
            expect(eventsToEmit[0].event).not.toBe(event)
            expect(eventsToEmit[0].event.properties).not.toHaveProperty('$browser')

            // Debug output entry keeps the original event object
            expect(eventsToEmit[1].event).toBe(event)
        })
    })

    describe('non-stripping mode (stripProperties=false)', () => {
        const step = createSplitFeatureFlagCallDebugStep(ENABLED_NO_STRIP)

        it('should send $feature_flag_called event unchanged to both outputs', async () => {
            const event = createProcessedEvent({
                $feature_flag: 'my-flag',
                $feature_flag_response: 'variant-a',
                $browser: 'Chrome',
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
            expect(eventsToEmit[0].event.properties).toHaveProperty('$browser', 'Chrome')

            expect(eventsToEmit[1].event).toBe(event)
            expect(eventsToEmit[1].output).toBe(FEATURE_FLAG_CALL_DEBUG_OUTPUT)
            expect(eventsToEmit[1].event.properties).toHaveProperty('$browser', 'Chrome')
        })

        it('should pass through non-$feature_flag_called events unchanged', async () => {
            const event = createProcessedEvent({ $browser: 'Chrome' }, { event: '$pageview' })

            const result = await step({ eventsToEmit: [{ event, output: EVENTS_OUTPUT }], teamId: 1 })
            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.eventsToEmit).toHaveLength(1)
            expect(result.value.eventsToEmit[0].event).toBe(event)
        })
    })
})
