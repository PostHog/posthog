import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'

import { findActionByType } from '../hogflow-utils'
import { ActionHandlerResult } from './action.interface'
import { DelayHandler, calculatedScheduledAt } from './delay'

describe('calculatedScheduledAt', () => {
    let startedAtTimestamp: number

    beforeEach(() => {
        const fixedTime = new Date('2025-01-01T00:00:00.000Z')
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
        startedAtTimestamp = DateTime.utc().toMillis()
    })

    describe('delay duration parsing', () => {
        it.each([
            ['1d', { days: 1 }],
            ['2h', { hours: 2 }],
            ['30m', { minutes: 30 }],
            ['45s', { seconds: 45 }],
            ['1.5h', { hours: 1.5 }],
        ])('should parse duration %s correctly', (duration, expected) => {
            const result = calculatedScheduledAt(duration, startedAtTimestamp)
            expect(result).toEqual(DateTime.utc().plus(expected))
        })

        it('should throw error for invalid duration format', () => {
            expect(() => calculatedScheduledAt('invalid', startedAtTimestamp)).toThrow('Invalid duration: invalid')
        })

        it('should throw error for invalid duration unit', () => {
            expect(() => calculatedScheduledAt('10x', startedAtTimestamp)).toThrow('Invalid duration: 10x')
        })
    })

    describe('delay timing', () => {
        it.each([
            ['1m', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ minutes: 1 })],
            ['2h', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ hours: 2 })],
            ['1d', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ days: 1 })],
        ])('should schedule for correct time with duration %s', (duration, expectedTime) => {
            const result = calculatedScheduledAt(duration, startedAtTimestamp)
            expect(result).toEqual(expectedTime)
        })

        it('should return null if delay time has already passed', () => {
            // Set start time to 1 hour ago
            const hourAgoTimestamp = DateTime.utc().minus({ hours: 1 }).toMillis()
            const result = calculatedScheduledAt('30m', hourAgoTimestamp)
            expect(result).toBeNull()

            const halfHourAgoTimestamp = DateTime.utc().minus({ minutes: 30 }).toMillis()
            const result2 = calculatedScheduledAt('31m', halfHourAgoTimestamp)
            expect(result2).toEqual(DateTime.utc().plus({ minutes: 1 }))
        })
    })

    describe('max delay duration', () => {
        it('should use max delay duration if provided and smaller than wait time', () => {
            const result = calculatedScheduledAt('2h', startedAtTimestamp, 300) // 5 minutes max
            expect(result).toEqual(DateTime.utc().plus({ seconds: 300 }))
        })

        it('should use wait time if smaller than max delay duration', () => {
            const result = calculatedScheduledAt('1m', startedAtTimestamp, 300) // 5 minutes max
            expect(result).toEqual(DateTime.utc().plus({ minutes: 1 }))
        })

        it.each([
            ['61s', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ seconds: 60 })],
            ['61m', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ minutes: 60 })],
            ['25h', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ hours: 24 })],
            ['31d', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ days: 30 })],
        ])('should enforce a maximum value for max delay duration', (duration, expectedTime) => {
            const result = calculatedScheduledAt(duration, startedAtTimestamp)
            expect(result).toEqual(expectedTime)
        })
    })

    describe('error handling', () => {
        it('should throw error if startedAtTimestamp is undefined', () => {
            expect(() => calculatedScheduledAt('1h', undefined)).toThrow(
                "'startedAtTimestamp' is not set or is invalid"
            )
        })

        it('should throw error if startedAtTimestamp is invalid', () => {
            expect(() => calculatedScheduledAt('1h', 0)).toThrow("'startedAtTimestamp' is not set or is invalid")
        })
    })
})

describe('DelayHandler with delay_until', () => {
    // Compiled by the HogQL compiler from `person.properties.trial_expiration_at`.
    const EXPIRY_BYTECODE = ['_H', 1, 32, 'trial_expiration_at', 32, 'properties', 32, 'person', 1, 3]
    const NOW = '2025-01-01T00:00:00.000Z'

    const buildDelay = (
        config: Record<string, any>,
        personProperties: Record<string, any> = {}
    ): { invocation: ReturnType<typeof createExampleHogFlowInvocation>; action: any } => {
        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    delay: { type: 'delay', config: config as any },
                    exit: { type: 'exit', config: {} },
                },
                edges: [{ from: 'delay', to: 'exit', type: 'continue' }],
            })
            .build()
        const action = findActionByType(hogFlow, 'delay')!
        const invocation = createExampleHogFlowInvocation(hogFlow, {}, { properties: personProperties })
        invocation.state.currentAction = {
            id: action.id,
            startedAtTimestamp: DateTime.fromISO(NOW).toMillis(),
        }
        return { invocation, action }
    }

    const runDelay = async (
        config: Record<string, any>,
        personProperties: Record<string, any> = {}
    ): Promise<ActionHandlerResult> => {
        const { invocation, action } = buildDelay(config, personProperties)
        return await new DelayHandler().execute({ invocation, action, result: {} as any })
    }

    const delayUntil = (overrides: Record<string, any> = {}): Record<string, any> => ({
        delay_until: {
            expression: 'person.properties.trial_expiration_at',
            bytecode: EXPIRY_BYTECODE,
            ...overrides,
        },
    })

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(NOW))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    // A stored date reaches the VM in whichever shape the customer set it, and all of these have to park to
    // the same instant — the step exists to follow their data rather than dictate a format.
    it.each([
        ['ISO string', '2025-01-08T00:00:00.000Z'],
        ['ISO string with no offset, read as UTC', '2025-01-08T00:00:00'],
        ['unix seconds', DateTime.fromISO('2025-01-08T00:00:00.000Z').toSeconds()],
        [
            'HogDateTime',
            { __hogDateTime__: true, dt: DateTime.fromISO('2025-01-08T00:00:00.000Z').toSeconds(), zone: 'UTC' },
        ],
    ])('parks until a date given as %s', async (_label, value) => {
        const result = await runDelay(delayUntil(), { trial_expiration_at: value })

        expect(result.scheduledAt?.toISO()).toBe(DateTime.fromISO('2025-01-08T00:00:00.000Z').toUTC().toISO())
        // Parking must not advance the step, or the matcher could wake the run and collapse the wait.
        expect(result.nextAction).toBeUndefined()
    })

    // Why a bare property picker is not enough: the reminder has to fire before the stored date.
    it.each([
        ['a day before', '-1d', '2025-01-07T00:00:00.000Z'],
        ['three days before', '-3d', '2025-01-05T00:00:00.000Z'],
        ['two hours after', '2h', '2025-01-08T02:00:00.000Z'],
    ])('applies an offset of %s', async (_label, offset, expected) => {
        const result = await runDelay(delayUntil({ offset }), { trial_expiration_at: '2025-01-08T00:00:00.000Z' })

        expect(result.scheduledAt?.toISO()).toBe(DateTime.fromISO(expected).toUTC().toISO())
    })

    it('continues immediately when the date has already passed', async () => {
        const result = await runDelay(delayUntil(), { trial_expiration_at: '2024-12-01T00:00:00.000Z' })

        expect(result.scheduledAt).toBeUndefined()
        expect(result.nextAction?.type).toBe('exit')
    })

    it('continues when the offset pulls the date into the past', async () => {
        // "Three days before" a date only one day out, so the reminder moment has already gone.
        const result = await runDelay(delayUntil({ offset: '-3d' }), {
            trial_expiration_at: '2025-01-02T00:00:00.000Z',
        })

        expect(result.nextAction?.type).toBe('exit')
    })

    // A fixed delay caps each unit ('45d' means 30 days). Carrying that into the offset would send a "45
    // days before" reminder 15 days late, and silently, so the offset keeps its full magnitude. The wait
    // stays bounded by max_delay_duration instead.
    it('keeps an offset larger than a fixed delay allows', async () => {
        const result = await runDelay(delayUntil({ offset: '-45d' }), {
            trial_expiration_at: '2025-03-02T00:00:00.000Z',
        })

        expect(result.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO('2025-01-16T00:00:00.000Z').toUTC().toISO())
    })

    // A ceiling nothing can parse must not read as zero: that puts the cap at the step's own start, so every
    // date resolves as already past and the next step runs at once.
    it('falls back to the default maximum when the configured one is unreadable', async () => {
        const result = await runDelay(
            { ...delayUntil(), max_delay_duration: 'whenever' },
            { trial_expiration_at: '2025-01-08T00:00:00.000Z' }
        )

        expect(result.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO('2025-01-08T00:00:00.000Z').toUTC().toISO())
        expect(result.nextAction).toBeUndefined()
    })

    it('clamps a far-future date to the default maximum', async () => {
        const result = await runDelay(delayUntil(), { trial_expiration_at: '2030-01-01T00:00:00.000Z' })

        // 30 days past the step's start, not five years: an unbounded park would strand the run.
        expect(result.scheduledAt?.toISO()).toBe(DateTime.fromISO(NOW).toUTC().plus({ days: 30 }).toISO())
    })

    // An offset whose magnitude overflows luxon's date range makes an invalid target: without a guard it
    // slips past the cap and hands the queue an unschedulable instant. It must clamp like '45d' or a
    // far-future date instead.
    it('clamps an offset too large to represent to the default maximum', async () => {
        const result = await runDelay(delayUntil({ offset: '100000000000000000000d' }), {
            trial_expiration_at: '2025-01-08T00:00:00.000Z',
        })

        expect(result.scheduledAt?.toISO()).toBe(DateTime.fromISO(NOW).toUTC().plus({ days: 30 }).toISO())
        expect(result.nextAction).toBeUndefined()
    })

    it('honours a configured maximum', async () => {
        const result = await runDelay(
            { ...delayUntil(), max_delay_duration: '2d' },
            { trial_expiration_at: '2025-01-08T00:00:00.000Z' }
        )

        expect(result.scheduledAt?.toISO()).toBe(DateTime.fromISO(NOW).toUTC().plus({ days: 2 }).toISO())
    })

    // Failing is deliberate. Continuing would run the next step at once, which for a "before X" reminder
    // sends the wrong message rather than none; erroring leaves the choice to the step's error handling.
    it.each([
        ['the property is missing', {}],
        ['the property is not a date', { trial_expiration_at: 'whenever' }],
        // A millisecond timestamp read as seconds lands in the year 58970; rejecting it stops the clamp from
        // silently turning it into a 30-day wait.
        ['the property is a unix millisecond timestamp', { trial_expiration_at: 1798761600000 }],
    ])('fails when %s', async (_label, personProperties) => {
        await expect(runDelay(delayUntil(), personProperties)).rejects.toThrow(
            'The date to wait for did not evaluate to a date'
        )
    })

    it('fails when the expression was never compiled', async () => {
        await expect(
            runDelay({ delay_until: { expression: 'person.properties.x', bytecode_error: 'boom' } })
        ).rejects.toThrow('Could not read the date to wait for: boom')
    })

    // A resume can rebuild globals without the person the expression reads, so the read raises rather than
    // returning null. The instant stored on the first park must still carry the run, not strand it.
    it('falls back to the saved instant when the expression errors on a resume', async () => {
        const { invocation, action } = buildDelay(delayUntil())
        invocation.state.currentAction!.delayUntilAt = '2025-01-08T00:00:00.000Z'
        delete (invocation.filterGlobals as any).person

        const result = await new DelayHandler().execute({ invocation, action, result: {} as any })

        expect(result.scheduledAt?.toISO()).toBe(DateTime.fromISO('2025-01-08T00:00:00.000Z').toUTC().toISO())
        expect(invocation.state.currentAction!.delayUntilUnresolved).toBeUndefined()
    })

    // With no saved instant to fall back on, the wait cannot resolve at all. It must mark itself unresolved
    // so the run aborts — otherwise on_error's default of continuing sends the message with nothing to be
    // before.
    it('marks the wait unresolved when the expression errors and no instant was saved', async () => {
        const { invocation, action } = buildDelay(delayUntil())
        delete (invocation.filterGlobals as any).person

        await expect(new DelayHandler().execute({ invocation, action, result: {} as any })).rejects.toThrow(
            'Could not read the date to wait for'
        )
        expect(invocation.state.currentAction!.delayUntilUnresolved).toBe(true)
    })

    // A date stored without a zone ('2025-01-08', or a local datetime) means midnight where the customer
    // is, not midnight UTC. Reading it in UTC sends a "day before" reminder on the wrong local day for
    // most of the world.
    it.each([
        ['UTC by default', {}, '2025-01-08T00:00:00.000Z'],
        ['a configured zone', { timezone: 'Asia/Tokyo' }, '2025-01-07T15:00:00.000Z'],
        ['a zone behind UTC', { timezone: 'America/New_York' }, '2025-01-08T05:00:00.000Z'],
    ])('reads a date with no offset of its own in %s', async (_label, zoneConfig, expected) => {
        const result = await runDelay(delayUntil(zoneConfig), { trial_expiration_at: '2025-01-08' })

        expect(result.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO(expected).toUTC().toISO())
    })

    // The zone only fills in what the value leaves out, so anything absolute must come out unchanged -
    // otherwise setting a zone would quietly move dates that were already exact.
    it.each([
        ['an offset-bearing string', '2025-01-08T00:00:00+00:00'],
        ['unix seconds', DateTime.fromISO('2025-01-08T00:00:00.000Z').toSeconds()],
    ])('leaves %s alone whatever the zone says', async (_label, value) => {
        const result = await runDelay(delayUntil({ timezone: 'Asia/Tokyo' }), { trial_expiration_at: value })

        expect(result.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO('2025-01-08T00:00:00.000Z').toUTC().toISO())
    })

    it("reads the date in the person's own timezone", async () => {
        const result = await runDelay(delayUntil({ use_person_timezone: true, fallback_timezone: 'Europe/Berlin' }), {
            trial_expiration_at: '2025-01-08',
            $geoip_time_zone: 'Asia/Tokyo',
        })

        expect(result.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO('2025-01-07T15:00:00.000Z').toUTC().toISO())
    })

    // Someone who travels, or whose GeoIP zone is corrected, must not be woken on their old local day. The
    // wait is read again when it ends, so the zone the person has then is the one that decides.
    it("follows the person's timezone when it changes while the run is parked", async () => {
        const { invocation, action } = buildDelay(delayUntil({ use_person_timezone: true, fallback_timezone: 'UTC' }), {
            trial_expiration_at: '2025-01-08',
            $geoip_time_zone: 'Asia/Tokyo',
        })

        const parked = await new DelayHandler().execute({ invocation, action, result: {} as any })
        expect(parked.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO('2025-01-07T15:00:00.000Z').toUTC().toISO())

        invocation.person!.properties.$geoip_time_zone = 'America/New_York'
        const onWake = await new DelayHandler().execute({ invocation, action, result: {} as any })

        expect(onWake.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO('2025-01-08T05:00:00.000Z').toUTC().toISO())
    })

    // Clocks go back in Berlin on 26 October 2025, so 02:30 that morning happens twice and the stored value
    // names two instants. Luxon takes the first. Locking that down stops a library change from moving such a
    // send by an hour unnoticed. The step's own clock moves to the day before, or the 30-day cap would
    // swallow a date ten months out.
    it('reads a local time inside a repeated hour as the first of the two', async () => {
        const dayBefore = '2025-10-25T00:00:00.000Z'
        jest.setSystemTime(new Date(dayBefore))
        const { invocation, action } = buildDelay(delayUntil({ timezone: 'Europe/Berlin' }), {
            trial_expiration_at: '2025-10-26T02:30:00',
        })
        invocation.state.currentAction!.startedAtTimestamp = DateTime.fromISO(dayBefore).toMillis()

        const result = await new DelayHandler().execute({ invocation, action, result: {} as any })

        expect(result.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO('2025-10-26T00:30:00.000Z').toUTC().toISO())
    })

    it('falls back when the person has no timezone', async () => {
        const result = await runDelay(delayUntil({ use_person_timezone: true, fallback_timezone: 'Europe/Berlin' }), {
            trial_expiration_at: '2025-01-08',
        })

        expect(result.scheduledAt?.toUTC().toISO()).toBe(DateTime.fromISO('2025-01-07T23:00:00.000Z').toUTC().toISO())
    })

    // A rerun of a failed run carries the marker in its stored state. Leaving it set would turn any later
    // failure of this step into an abort, whatever the step's error handling says.
    it('clears the unresolved marker once the wait resolves', async () => {
        const { invocation, action } = buildDelay(delayUntil(), { trial_expiration_at: '2025-01-08T00:00:00.000Z' })
        invocation.state.currentAction!.delayUntilUnresolved = true

        await new DelayHandler().execute({ invocation, action, result: {} as any })

        expect(invocation.state.currentAction!.delayUntilUnresolved).toBeUndefined()
    })

    // HogQL returns a HogDateTime holding whatever it parsed, so toDateTime('not a date') arrives as NaN
    // seconds. Without a check that becomes an instant the queue cannot schedule, rather than a wait that
    // could not work out its date.
    it.each([
        ['NaN', NaN],
        ['Infinity', Infinity],
    ])('fails on a HogDateTime holding %s', async (_label, seconds) => {
        await expect(
            runDelay(delayUntil(), { trial_expiration_at: { __hogDateTime__: true, dt: seconds, zone: 'UTC' } })
        ).rejects.toThrow('The date to wait for did not evaluate to a date')
    })

    it('still delays by a fixed duration when that is what is configured', async () => {
        const result = await runDelay({ delay_duration: '2h' })

        expect(result.scheduledAt?.toISO()).toBe(DateTime.fromISO(NOW).toUTC().plus({ hours: 2 }).toISO())
    })
})
