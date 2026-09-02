import { register } from 'prom-client'

import { HogFlow } from '~/cdp/schema/hogflow'

import { createExampleHogFlowInvocation } from '../../_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '../../types'
import {
    DEFAULT_CONVERSION_WINDOW_MINUTES,
    MAX_CONVERSION_WINDOW_MINUTES,
    MAX_LEGACY_WINDOW_MINUTES,
    buildConversionWatcher,
} from './conversion-watcher'

describe('buildConversionWatcher', () => {
    const propertyBytecode = ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 32, 'person', 1, 3, 11]
    const eventBytecode = ['_H', 1, 32, 'signed_up', 32, 'event', 1, 1, 11]

    const propertyGoal = {
        filters: [{ key: '$browser', type: 'person', value: ['Chrome'], operator: 'exact' }],
        bytecode: propertyBytecode,
        window_minutes: null,
    }
    const eventGoal = {
        filters: [],
        bytecode: [],
        window_minutes: null,
        events: [{ filters: { events: [{ id: 'signed_up' }], bytecode: eventBytecode } }],
    }
    const noGoal = { filters: [], bytecode: [], window_minutes: null }

    const invocationFor = (conversion: any, flowOverrides: Partial<HogFlow> = {}): CyclotronJobInvocationHogFlow => {
        const hogFlow = { id: 'flow-1', team_id: 1, version: 3, conversion, ...flowOverrides } as unknown as HogFlow
        // Every production dispatch path seeds flowVersion when it builds the invocation
        // (createHogFlowInvocation, and the batch-resolve consumer); the shared fixture does not.
        return createExampleHogFlowInvocation(hogFlow, { flowVersion: hogFlow.version })
    }

    it.each([
        ['a property goal', propertyGoal, true],
        ['an event goal', eventGoal, true],
        ['no goal configured', noGoal, false],
    ])('builds a watcher for a workflow with %s', (_name, conversion, expected) => {
        expect(buildConversionWatcher(invocationFor(conversion)) !== null).toBe(expected)
    })

    it('carries the ids the matcher and the conversion query both need', () => {
        const invocation = invocationFor(propertyGoal)

        expect(buildConversionWatcher(invocation)).toMatchObject({
            run_id: invocation.id,
            function_id: 'flow-1',
            team_id: 1,
            distinct_id: 'distinct_id',
            // Pinned from state, so a conversion divides by a denominator of the same version.
            flow_version: 3,
        })
    })

    it('pins the goal as it stood at enrollment', () => {
        // Read from the watcher rather than the live flow, so editing a goal changes what later runs
        // are measured against without re-judging cohorts already in flight under the old one.
        expect(buildConversionWatcher(invocationFor(propertyGoal))?.goal).toEqual({ properties: propertyBytecode })
        expect(buildConversionWatcher(invocationFor(eventGoal))?.goal).toEqual({ events: [eventBytecode] })
    })

    it('drops an event goal that targets neither an event nor an action', () => {
        // Such an entry compiles to always-true bytecode, which would convert on the first event of
        // any kind. The wait_until and conversion evaluators guard it, so the watcher must too.
        const emptyTarget = {
            filters: [],
            bytecode: [],
            window_minutes: null,
            events: [{ filters: { bytecode: [1] } }],
        }

        expect(buildConversionWatcher(invocationFor(emptyTarget))).toBeNull()
    })

    it.each([
        ['no configured window', null, DEFAULT_CONVERSION_WINDOW_MINUTES],
        ['a legacy window longer than its cap', 604800, MAX_LEGACY_WINDOW_MINUTES],
        ['a legacy window inside its cap', 60, 60],
    ])('expires after %s', (_name, windowMinutes, expectedMinutes) => {
        // Treating null as "forever" would leave rows the expiry sweep can never reach.
        const before = Date.now()
        const watcher = buildConversionWatcher(invocationFor({ ...propertyGoal, window_minutes: windowMinutes }))

        // Measured from `before`, so the window is at least the expected value and at most a
        // fraction of a minute more.
        const minutes = (watcher!.expires_at.getTime() - before) / 60_000
        expect(minutes).toBeGreaterThanOrEqual(expectedMinutes)
        expect(minutes).toBeLessThan(expectedMinutes + 1)
    })

    it.each([
        ['a duration string', { window: '7d' }, 7 * 24 * 60],
        ['hours', { window: '12h' }, 12 * 60],
        ['a duration string past the cap', { window: '400d' }, MAX_CONVERSION_WINDOW_MINUTES],
        // The duration string is the trustworthy form, so it wins over a bare number that may hold
        // any unit at all.
        ['both forms set', { window: '7d', window_minutes: 604800 }, 7 * 24 * 60],
    ])('expires after %s', (_name, conversionWindow, expectedMinutes) => {
        const before = Date.now()
        const watcher = buildConversionWatcher(invocationFor({ ...propertyGoal, ...conversionWindow }))

        const minutes = (watcher!.expires_at.getTime() - before) / 60_000
        expect(minutes).toBeGreaterThanOrEqual(expectedMinutes)
        expect(minutes).toBeLessThan(expectedMinutes + 1)
    })

    it('counts a run whose window was shortened to the cap, and only then', async () => {
        // The clamp changes what the workflow's conversion rate measures. Without this counter the
        // substitution leaves no trace anywhere, which is how it went unnoticed in the first place.
        const clamped = async (): Promise<number> =>
            ((await register.getSingleMetric('cdp_conversion_window_clamped')?.get())?.values[0]?.value as number) ?? 0

        const before = await clamped()

        buildConversionWatcher(invocationFor({ ...propertyGoal, window_minutes: MAX_LEGACY_WINDOW_MINUTES + 1 }))
        expect(await clamped()).toBe(before + 1)

        buildConversionWatcher(invocationFor({ ...propertyGoal, window_minutes: MAX_LEGACY_WINDOW_MINUTES }))
        expect(await clamped()).toBe(before + 1)
    })

    it('counts a run whose stored window string could not be parsed, and only then', async () => {
        // A stored window the worker cannot parse falls back to the default, changing what the run
        // measures. The counter is the only signal that happened, so it must fire on the fallback path.
        const invalidCount = async (): Promise<number> =>
            ((await register.getSingleMetric('cdp_conversion_window_invalid')?.get())?.values[0]?.value as number) ?? 0

        const before = await invalidCount()

        // An unparseable window (e.g. a non-ASCII digit reaching storage past validation) falls back to
        // the default window and increments the counter.
        const fallback = buildConversionWatcher(invocationFor({ ...propertyGoal, window: '٧d' }))
        const start = Date.now()
        const minutes = (fallback!.expires_at.getTime() - start) / 60_000
        expect(minutes).toBeGreaterThanOrEqual(DEFAULT_CONVERSION_WINDOW_MINUTES)
        expect(minutes).toBeLessThan(DEFAULT_CONVERSION_WINDOW_MINUTES + 1)
        expect(await invalidCount()).toBe(before + 1)

        // A parseable window does not touch the counter.
        buildConversionWatcher(invocationFor({ ...propertyGoal, window: '7d' }))
        expect(await invalidCount()).toBe(before + 1)
    })

    it('does not build a watcher for a run that has already started', () => {
        // A run with several delays would otherwise enroll once per wake, inflating the denominator
        // and the row count together.
        const invocation = invocationFor(propertyGoal)
        invocation.state.currentAction = { id: 'some_action', startedAtTimestamp: Date.now() }

        expect(buildConversionWatcher(invocation)).toBeNull()
    })
})
