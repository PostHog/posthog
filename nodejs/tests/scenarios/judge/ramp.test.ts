import type { Named, Step } from '../cards'
import type { DrivenStep, StepWindow } from '../generator/generator'
import type { TruthRecord } from '../provider-edge'
import { type BarEvidence, type BarResult, type CpuPoint, judgeBars } from './bars'
import type { Convergence, InvariantResult, JournalEntry } from './judge'
import { type MetricSample, SCRAPE_GAP_MS } from './measurements'
import { Broke, LiveRamp, Ramp, RampEvidence, RampStop, StepRates, rampOf, stepRatesOf, watchRamp } from './ramp'

const T = Date.UTC(2026, 0, 5, 10, 0, 0)
const MINUTE = 60_000
const STEPS: Step[] = [
    { scale: 1, fromMs: 0, toMs: 2 * MINUTE },
    { scale: 2, fromMs: 2 * MINUTE, toMs: 4 * MINUTE },
    { scale: 5, fromMs: 4 * MINUTE, toMs: 6 * MINUTE },
]
const UNITS_PER_STEP = [120, 240, 600]
const WRITER_CPU: Named = { name: 'writer_cpu_under', params: { percent: 70 } }
const PICKUP: Named = { name: 'pickup_p99_under', params: { seconds: 5, queues: ['email'] } }
const iso = (at: number): string => new Date(at).toISOString()

const driven = (index: number, offeredUnits = UNITS_PER_STEP[index]): DrivenStep => ({
    index,
    scale: STEPS[index].scale,
    startedAt: T + STEPS[index].fromMs,
    endedAt: T + STEPS[index].toMs,
    dueUnits: UNITS_PER_STEP[index],
    offeredUnits,
})

const unit = (step: number, i: number, accepted = true): JournalEntry => ({
    unitId: `u-${step}-${i}`,
    kind: 'transactional',
    teamId: 7,
    offeredAt: T + STEPS[step].fromMs + i * 1000,
    step,
    answer: accepted ? { accepted: true } : { accepted: false, status: 503 },
    expect: { deliveries: ['email'] },
})

const cpuByMinute = (percents: number[]): CpuPoint[] =>
    percents.map((percent, minute) => ({ at: T + minute * MINUTE, percent }))

const scrapedEvery5s = (
    untilS: number,
    at: (atS: number) => Pick<MetricSample, 'processed' | 'lateness'>
): MetricSample[] =>
    Array.from({ length: untilS / 5 + 1 }, (_, i) => i * 5).map((atS) => ({
        role: 'cdp-cyclotron-worker-email',
        replica: 0,
        at: T + atS * 1000,
        startedAt: T / 1000 - 60,
        cpuSeconds: 1,
        rssBytes: 1,
        pgClientErrors: 0,
        consumerLoopErrors: 0,
        janitorStalled: 0,
        ...at(atS),
    }))

const pickups = (prompt: number): MetricSample['lateness'] => ({
    email: { '1': prompt, '5': prompt, '10': prompt, '+Inf': prompt },
})

const claiming = (perSecond: number) => (atS: number) => ({
    processed: { hogflow: atS * perSecond },
    lateness: pickups(atS),
})

const NEVER = new AbortController().signal

function live(overrides: Partial<LiveRamp> = {}): LiveRamp {
    return {
        minOffered: 0.9,
        bars: [WRITER_CPU],
        gates: { refused_at_intake: 0 },
        judgesRefusals: true,
        driveStartedAt: T,
        journal: () => [],
        samples: () => [],
        host: () => [],
        queue: () => [],
        profile: {},
        writerCpu: () => Promise.resolve(cpuByMinute([40, 40, 80, 80, 90, 90])),
        ...overrides,
    }
}

const windowOf = (index: number): StepWindow => {
    const { offeredUnits: _offered, ...window } = driven(index)
    return window
}

describe('ramp', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: T + 6 * MINUTE })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each<[string, Partial<LiveRamp>, number, number, { advance: boolean; stop: RampStop | undefined }]>([
        [
            'passes a step whose bars held, so the generator moves to the next scale',
            {},
            0,
            UNITS_PER_STEP[0],
            { advance: true, stop: undefined },
        ],
        [
            'goes on past a step whose bar broke, since a broken bar is no hard failure',
            {},
            1,
            UNITS_PER_STEP[1],
            { advance: true, stop: undefined },
        ],
        [
            'ends at a harness limit when a sibling of a broken bar could not be read in the same step',
            { bars: [WRITER_CPU, PICKUP] },
            1,
            UNITS_PER_STEP[1],
            {
                advance: false,
                stop: expect.objectContaining({
                    end: 'harness_limit',
                    broke: expect.objectContaining({ by: 'run_host', kind: 'harness', scale: 2 }),
                }),
            },
        ],
        [
            'ends at a step the generator could not offer, even when its bar broke there',
            {},
            1,
            200,
            {
                advance: false,
                stop: {
                    index: 1,
                    end: 'harness_limit',
                    reason: 'the generator offered 200 of 240 units in the 2x step, under minOffered 0.9',
                    broke: {
                        scale: 2,
                        offeredPerSecond: 200 / 120,
                        by: 'generator',
                        kind: 'harness',
                        at: iso(T + 2 * MINUTE),
                        part: null,
                    },
                },
            },
        ],
        [
            'ends at a first step whose workers claimed under the profile load, before any bar is read',
            {
                profile: { load: { targets: { claimsPerSecond: { hogflow: 5 } }, tolerance: 0.2 } },
                samples: () => scrapedEvery5s(135, claiming(1)),
                writerCpu: () => Promise.reject(new Error('read before the admission')),
            },
            0,
            UNITS_PER_STEP[0],
            {
                advance: false,
                stop: expect.objectContaining({
                    index: 0,
                    end: 'harness_limit',
                    reason: 'the load admission failed at the 1x step: hogflow claims 1/s, not within 20% of 5/s',
                    broke: expect.objectContaining({ by: 'generator', kind: 'harness', scale: 1 }),
                }),
            },
        ],
        [
            'ends at a step the target says to halt at, before its bars are read',
            {
                targetLimit: ({ scale }) => Promise.resolve(`dev quota limited 3 runs at the ${scale}x step`),
                writerCpu: () => Promise.reject(new Error('read after the target halted')),
            },
            1,
            UNITS_PER_STEP[1],
            {
                advance: false,
                stop: expect.objectContaining({
                    index: 1,
                    end: 'harness_limit',
                    reason: 'dev quota limited 3 runs at the 2x step',
                    broke: expect.objectContaining({ by: 'target', kind: 'harness', scale: 2 }),
                }),
            },
        ],
        [
            'passes a first step whose workers claimed at the profile load',
            {
                profile: { load: { targets: { claimsPerSecond: { hogflow: 5 } }, tolerance: 0.2 } },
                samples: () => scrapedEvery5s(135, claiming(5)),
            },
            0,
            UNITS_PER_STEP[0],
            { advance: true, stop: undefined },
        ],
        [
            'ends at a harness limit when the live judge itself fails, rather than rejecting the drive',
            {
                samples: () => {
                    throw new Error('socket hang up')
                },
            },
            1,
            UNITS_PER_STEP[1],
            {
                advance: false,
                stop: expect.objectContaining({
                    end: 'harness_limit',
                    reason: 'the live judge failed at the 2x step: socket hang up',
                    broke: expect.objectContaining({ by: 'run_host', kind: 'harness', scale: 2 }),
                }),
            },
        ],
        [
            'goes on past a step whose bar has no source on this stack',
            {
                writerCpu: () =>
                    Promise.resolve({ unsourced: 'the local stack has no Aurora writer to read CPU from' }),
            },
            0,
            UNITS_PER_STEP[0],
            { advance: true, stop: undefined },
        ],
        [
            'ends at a step whose bar the run host could not read',
            { writerCpu: () => Promise.resolve({ unread: 'CloudWatch returned no datapoints' }) },
            0,
            UNITS_PER_STEP[0],
            {
                advance: false,
                stop: expect.objectContaining({
                    end: 'harness_limit',
                    broke: expect.objectContaining({ by: 'run_host', kind: 'harness', scale: 1 }),
                }),
            },
        ],
        [
            'ends at a harness limit, not a break, when a writer CPU minute came back without a value',
            {
                writerCpu: () =>
                    Promise.resolve([
                        { at: T, percent: undefined as unknown as number },
                        { at: T + MINUTE, percent: 40 },
                    ]),
            },
            0,
            UNITS_PER_STEP[0],
            {
                advance: false,
                stop: expect.objectContaining({
                    end: 'harness_limit',
                    reason: `writer_cpu_under was not judged: no writer CPU reading for the minute at ${iso(T)} in the 1x step`,
                    broke: expect.objectContaining({ by: 'run_host', kind: 'harness', scale: 1 }),
                }),
            },
        ],
        [
            'ends at a harness limit, not the pickup bar the step broke, when the writer CPU read failed',
            {
                bars: [WRITER_CPU, PICKUP],
                samples: () =>
                    scrapedEvery5s(135, (atS) => ({
                        processed: {},
                        lateness: { email: { '1': 0, '5': 0, '10': atS, '+Inf': atS } },
                    })),
                writerCpu: () => Promise.reject(new Error('socket hang up')),
            },
            0,
            UNITS_PER_STEP[0],
            {
                advance: false,
                stop: expect.objectContaining({
                    index: 0,
                    end: 'harness_limit',
                    broke: expect.objectContaining({ by: 'run_host', kind: 'harness', scale: 1 }),
                }),
            },
        ],
        [
            'passes a pickup-only card without reading the writer CPU',
            {
                bars: [PICKUP],
                samples: () => scrapedEvery5s(135, (atS) => ({ processed: {}, lateness: pickups(atS) })),
                writerCpu: () => {
                    throw new Error('no writer bar on this card')
                },
            },
            0,
            UNITS_PER_STEP[0],
            { advance: true, stop: undefined },
        ],
    ])('%s', async (_story, overrides, index, offered, expected) => {
        jest.setSystemTime(windowOf(index).endedAt)
        const watch = watchRamp(live(overrides), NEVER)

        const verdict = watch.gate(windowOf(index), () => offered)
        await jest.advanceTimersByTimeAsync(SCRAPE_GAP_MS)
        await verdict

        expect({ advance: !watch.halt.aborted, stop: watch.stopped() }).toEqual(expected)
    })

    it('stops at a step whose runner lagged and so offered short, naming the runner', async () => {
        jest.setSystemTime(windowOf(1).endedAt)
        const watch = watchRamp(live(), NEVER)

        const verdict = watch.gate({ ...windowOf(1), loopLagP99Ms: 900 }, () => 200)
        await jest.advanceTimersByTimeAsync(SCRAPE_GAP_MS)
        await verdict

        expect(watch.stopped()).toMatchObject({
            index: 1,
            end: 'harness_limit',
            reason: "the runner's event loop lagged 900 ms at p99 in the 2x step, over 250 ms",
            broke: { by: 'runner', kind: 'harness', scale: 2 },
        })
    })

    it('admits a first step at 5x whose workers claimed five times the 1x load target', async () => {
        const opener = { ...windowOf(0), scale: 5 }
        jest.setSystemTime(opener.endedAt)
        const watch = watchRamp(
            live({
                profile: { load: { targets: { claimsPerSecond: { hogflow: 1 } }, tolerance: 0.2 } },
                samples: () => scrapedEvery5s(135, claiming(5)),
            }),
            NEVER
        )

        const verdict = watch.gate(opener, () => UNITS_PER_STEP[0])
        await jest.advanceTimersByTimeAsync(SCRAPE_GAP_MS)
        await verdict

        expect({ advance: !watch.halt.aborted, stop: watch.stopped() }).toEqual({ advance: true, stop: undefined })
    })

    it('takes no refusal recorded after the run was cancelled', () => {
        const run = new AbortController()
        const watch = watchRamp(live(), run.signal)
        run.abort()

        watch.record(unit(1, 3, false))

        expect({ halted: watch.halt.aborted, stop: watch.stopped() }).toEqual({ halted: false, stop: undefined })
    })

    it('leaves no verdict when the run is cancelled while a writer CPU read is pending', async () => {
        jest.setSystemTime(windowOf(0).endedAt)
        const run = new AbortController()
        const watch = watchRamp(
            live({
                writerCpu: () =>
                    new Promise((_resolve, reject) =>
                        run.signal.addEventListener('abort', () => reject(new Error('aws cloudwatch was cancelled')))
                    ),
            }),
            run.signal
        )

        const verdict = watch.gate(windowOf(0), () => UNITS_PER_STEP[0])
        await jest.advanceTimersByTimeAsync(SCRAPE_GAP_MS)
        run.abort()
        await verdict

        expect({ halted: watch.halt.aborted, stop: watch.stopped() }).toEqual({ halted: false, stop: undefined })
    })

    it('judges a step only once its last scrape interval has passed', async () => {
        jest.setSystemTime(driven(0).endedAt)
        const watch = watchRamp(live(), NEVER)
        let settled = false
        void watch.gate(windowOf(0), () => UNITS_PER_STEP[0]).then(() => (settled = true))

        await jest.advanceTimersByTimeAsync(SCRAPE_GAP_MS - 1)
        const early = settled
        await jest.advanceTimersByTimeAsync(1)

        expect({ early, settled, halted: watch.halt.aborted }).toEqual({ early: false, settled: true, halted: false })
    })

    it.each<[string, number, JournalEntry[], number | undefined]>([
        ['the first refusal over a gate of 0, in the last step', 0, [unit(2, 3, false)], 2],
        ['the first refusal over a fractional gate', 0.5, [unit(1, 3, false)], 1],
        ['the first refusal over a negative gate', -1, [unit(1, 3, false)], 1],
        [
            'the refusal that crossed the gate by offer time, not the one journaled last',
            1,
            [unit(1, 3, false), unit(0, 9, false)],
            1,
        ],
        [
            'the higher step when its refusal shares an offer time with a lower step and was journaled first',
            1,
            [unit(1, 0, false), unit(0, 120, false)],
            1,
        ],
        ['no stop while the refusals stay within the gate', 1, [unit(1, 3, false)], undefined],
        ['no stop for an accepted unit', 0, [unit(1, 3)], undefined],
        [
            'the lower step whose refusal answered after a refusal in a higher step halted the drive',
            0,
            [unit(2, 3, false), unit(1, 3, false)],
            1,
        ],
        [
            'the lower step whose refusals answered after two refusals in a higher step crossed the gate',
            1,
            [unit(2, 3, false), unit(2, 6, false), unit(1, 3, false), unit(0, 5, false)],
            1,
        ],
    ])('halts the drive at %s', (_story, gate, journal, index) => {
        const watch = watchRamp(live({ gates: { refused_at_intake: gate } }), NEVER)

        journal.forEach((entry) => watch.record(entry))

        expect({ halted: watch.halt.aborted, index: watch.stopped()?.index }).toEqual({
            halted: index !== undefined,
            index,
        })
    })

    it('stops at the first step when an intake held past its end answers a refusal while the writer CPU read is pending', async () => {
        jest.setSystemTime(windowOf(0).endedAt)
        let read: ((points: CpuPoint[]) => void) | undefined
        const watch = watchRamp(live({ writerCpu: () => new Promise((resolve) => (read = resolve)) }), NEVER)
        let answer: ((entry: JournalEntry) => void) | undefined
        void new Promise<JournalEntry>((resolve) => (answer = resolve)).then((entry) => watch.record(entry))

        const verdict = watch.gate(windowOf(0), () => UNITS_PER_STEP[0])
        await jest.advanceTimersByTimeAsync(SCRAPE_GAP_MS)
        const beforeTheAnswer = watch.halt.aborted
        answer!(unit(0, 119, false))
        await jest.advanceTimersByTimeAsync(0)
        read!(cpuByMinute([40, 40]))
        await verdict

        expect({ beforeTheAnswer, advance: !watch.halt.aborted, stop: watch.stopped() }).toEqual({
            beforeTheAnswer: false,
            advance: false,
            stop: {
                index: 0,
                end: 'broke',
                reason: 'refused_at_intake went over its gate of 0 with 1 refused',
            },
        })
    })

    it('waits for a pending read and keeps the break it finds at a lower step for the verdict after a refusal in a later step halted the drive', async () => {
        jest.setSystemTime(windowOf(0).endedAt)
        let read: ((points: CpuPoint[]) => void) | undefined
        const watch = watchRamp(live({ writerCpu: () => new Promise((resolve) => (read = resolve)) }), NEVER)

        void watch.gate(windowOf(0), () => UNITS_PER_STEP[0])
        await jest.advanceTimersByTimeAsync(SCRAPE_GAP_MS)
        watch.record(unit(1, 3, false))
        const pending = watch.pending()
        read!(cpuByMinute([90, 90]))
        await pending

        expect({ stop: watch.stopped(), settled: watch.settled().get(0) }).toMatchObject({
            stop: { index: 1, end: 'broke', reason: 'refused_at_intake went over its gate of 0 with 1 refused' },
            settled: [{ name: 'writer_cpu_under', breakingPoint: { scale: 1 } }],
        })
    })

    const STEPS_DRIVEN = [driven(0), driven(1), driven(2)]
    const JOURNAL = [unit(0, 3), unit(1, 7), unit(2, 3)]
    const held = (name = 'writer_cpu_under'): BarResult => ({ name, unit: '%', limit: 70, passed: true })
    const brokeAt = (scale: number, part = 'db:cyclotron'): BarResult => ({
        name: 'writer_cpu_under',
        unit: '%',
        limit: 70,
        passed: false,
        breakingPoint: { scale, at: iso(T), offeredPerSecond: 5, value: 91, part },
    })
    const unreadAt = (scale: number): BarResult => ({
        name: 'writer_cpu_under',
        unit: '%',
        limit: 70,
        passed: false,
        unjudged: `no writer CPU reading in the ${scale}x step`,
        harnessLimit: { scale, by: 'run_host' },
    })
    const failed = (name: string, crossedBy?: string): InvariantResult => ({
        name,
        passed: false,
        observed: 1,
        unitIds: crossedBy ? [crossedBy] : [],
        ...(crossedBy && { crossedBy }),
    })
    const harnessAt = (
        index: number,
        by: 'generator' | 'run_host' | 'runner',
        offeredUnits = UNITS_PER_STEP[index]
    ): Broke => ({
        scale: STEPS[index].scale,
        offeredPerSecond: offeredUnits / 120,
        by,
        kind: 'harness',
        at: iso(T + STEPS[index].fromMs),
        part: null,
    })

    const lostAt = (lost: Record<number, number>): StepRates[] =>
        STEPS_DRIVEN.map(({ index, scale }) => {
            const expected = UNITS_PER_STEP[index]
            const missed = lost[index] ?? 0
            return {
                index,
                scale,
                expected,
                lost: missed,
                lossRate: missed / expected,
                sent: expected - missed,
                duplicates: 0,
                duplicateRate: 0,
                refused: 0,
                refusedRate: 0,
            }
        })
    const barAt5: Broke = {
        scale: 5,
        offeredPerSecond: 5,
        by: 'writer_cpu_under',
        kind: 'bar',
        at: iso(T),
        part: 'db:cyclotron',
    }
    const lossAt2 = '13 of 240 deliveries were lost in the 2x step (5.42%), over the 5% hard limit'
    const backlog = 'the backlog did not drain within convergeWithin: 1 job stayed unfinished'
    const undrained: Broke = {
        scale: null,
        offeredPerSecond: null,
        by: 'convergence',
        kind: 'invariant',
        at: null,
        part: null,
    }

    const limited = (ramp: Ramp): Ramp => ({
        ...ramp,
        stop: { failure: 'harness_limit', scale: ramp.broke?.scale ?? null, reason: ramp.reason },
    })

    it.each<[string, Partial<RampEvidence>, Ramp]>([
        [
            'a bar that broke at a step, after the steps below it held',
            { bars: [brokeAt(5)] },
            {
                end: 'broke',
                sustainedScale: 2,
                broke: {
                    scale: 5,
                    offeredPerSecond: 5,
                    by: 'writer_cpu_under',
                    kind: 'bar',
                    at: iso(T),
                    part: 'db:cyclotron',
                },
                reason: 'writer_cpu_under broke at the 5x step',
            },
        ],
        [
            'a delivery lost under the hard limit below the step where a bar broke, which the ramp records and runs past',
            { bars: [brokeAt(5)], invariants: [failed('at_least_once', 'u-1-7')], rates: lostAt({ 1: 1 }) },
            {
                end: 'broke',
                sustainedScale: 2,
                broke: barAt5,
                reason: 'writer_cpu_under broke at the 5x step',
                rates: lostAt({ 1: 1 }),
            },
        ],
        [
            'a step that lost exactly 5% of its deliveries, which is no hard failure',
            { invariants: [failed('at_least_once', 'u-1-7')], rates: lostAt({ 1: 12 }) },
            {
                end: 'ceiling',
                sustainedScale: 5,
                reason: 'every step held up to the 5x ceiling',
                rates: lostAt({ 1: 12 }),
            },
        ],
        [
            'a step that lost more than 5% of its deliveries, below the step where a bar broke',
            { bars: [brokeAt(5)], invariants: [failed('at_least_once', 'u-1-7')], rates: lostAt({ 1: 13 }) },
            {
                end: 'broke',
                sustainedScale: 1,
                broke: {
                    scale: 2,
                    offeredPerSecond: 2,
                    by: 'at_least_once',
                    kind: 'invariant',
                    at: iso(T + 2 * MINUTE),
                    part: null,
                },
                reason: lossAt2,
                stop: { failure: 'step_loss', scale: 2, reason: lossAt2 },
                rates: lostAt({ 1: 13 }),
            },
        ],
        [
            'duplicates over their gate at the first step, which the ramp records and runs past',
            { invariants: [failed('duplicate_sends', 'u-0-3')], gates: { duplicate_sends: 0 } },
            { end: 'ceiling', sustainedScale: 5, reason: 'every step held up to the 5x ceiling' },
        ],
        [
            'an invariant that failed with no crossing unit in any step, which is no hard failure',
            { invariants: [failed('resident_backlog_intact')] },
            { end: 'ceiling', sustainedScale: 5, reason: 'every step held up to the 5x ceiling' },
        ],
        [
            'a bar that broke at a step while an invariant failed with no crossing unit in any step',
            { bars: [brokeAt(5)], invariants: [failed('resident_backlog_intact')] },
            {
                end: 'broke',
                sustainedScale: 2,
                broke: {
                    scale: 5,
                    offeredPerSecond: 5,
                    by: 'writer_cpu_under',
                    kind: 'bar',
                    at: iso(T),
                    part: 'db:cyclotron',
                },
                reason: 'writer_cpu_under broke at the 5x step',
            },
        ],
        [
            'a last step the generator offered short, which is no ceiling',
            { steps: [driven(0), driven(1), driven(2, 510)] },
            limited({
                end: 'harness_limit',
                sustainedScale: 2,
                broke: harnessAt(2, 'generator', 510),
                reason: 'the generator offered 510 of 600 units in the 5x step, under minOffered 0.9',
            }),
        ],
        [
            'a step offered short below the step where a bar broke',
            { steps: [driven(0), driven(1, 200), driven(2)], bars: [brokeAt(5)] },
            limited({
                end: 'harness_limit',
                sustainedScale: 1,
                broke: harnessAt(1, 'generator', 200),
                reason: 'the generator offered 200 of 240 units in the 2x step, under minOffered 0.9',
            }),
        ],
        [
            "a step where the runner's event loop lagged, below the step where a bar broke",
            { steps: [driven(0), { ...driven(1), loopLagP99Ms: 900 }, driven(2)], bars: [brokeAt(5)] },
            limited({
                end: 'harness_limit',
                sustainedScale: 1,
                broke: harnessAt(1, 'runner'),
                reason: "the runner's event loop lagged 900 ms at p99 in the 2x step, over 250 ms",
            }),
        ],
        [
            'a step whose runner lagged and so offered short, which the runner outranks',
            { steps: [driven(0), { ...driven(1, 200), loopLagP99Ms: 900 }, driven(2)], bars: [brokeAt(5)] },
            limited({
                end: 'harness_limit',
                sustainedScale: 1,
                broke: harnessAt(1, 'runner', 200),
                reason: "the runner's event loop lagged 900 ms at p99 in the 2x step, over 250 ms",
            }),
        ],
        [
            'a last step whose bar the run host could not read',
            { bars: [unreadAt(5)] },
            limited({
                end: 'harness_limit',
                sustainedScale: 2,
                broke: harnessAt(2, 'run_host'),
                reason: 'writer_cpu_under was not judged: no writer CPU reading in the 5x step',
            }),
        ],
        [
            'a first step whose schedule held no units, which sustains nothing',
            { steps: [{ ...driven(0, 0), dueUnits: 0 }, driven(1), driven(2)], bars: [brokeAt(5)] },
            limited({
                end: 'harness_limit',
                sustainedScale: null,
                broke: harnessAt(0, 'generator', 0),
                reason: 'the generator had no units to offer in the 1x step',
            }),
        ],
        [
            'a baseline that failed its load admission, so no scale was sustained',
            {
                admissions: [{ name: 'load', passed: false, reason: 'hogflow claims ran at 1/s, under 5/s' }],
            },
            limited({
                end: 'harness_limit',
                sustainedScale: null,
                broke: harnessAt(0, 'generator'),
                reason: 'the load admission failed at the 1x step: hogflow claims ran at 1/s, under 5/s',
            }),
        ],
        [
            'a first step whose runner lagged while its load admission failed, which the runner outranks',
            {
                steps: [{ ...driven(0), loopLagP99Ms: 900 }, driven(1), driven(2)],
                admissions: [{ name: 'load', passed: false, reason: 'hogflow claims ran at 1/s, under 5/s' }],
            },
            limited({
                end: 'harness_limit',
                sustainedScale: null,
                broke: harnessAt(0, 'runner'),
                reason: "the runner's event loop lagged 900 ms at p99 in the 1x step, over 250 ms",
            }),
        ],
        [
            'a last step the drive was interrupted in, which is no ceiling',
            { steps: [driven(0), driven(1), { ...driven(2, 100), endedAt: T + 4 * MINUTE + 20_000, dueUnits: 100 }] },
            limited({
                end: 'harness_limit',
                sustainedScale: 2,
                broke: { ...harnessAt(2, 'generator'), offeredPerSecond: 5 },
                reason: 'the drive ended during the 5x step',
            }),
        ],
        [
            'a last step the drive was interrupted in before the run host could read its bar',
            {
                steps: [driven(0), driven(1), { ...driven(2, 100), endedAt: T + 4 * MINUTE + 20_000, dueUnits: 100 }],
                bars: [unreadAt(5)],
            },
            limited({
                end: 'harness_limit',
                sustainedScale: 2,
                broke: { ...harnessAt(2, 'generator'), offeredPerSecond: 5 },
                reason: 'the drive ended during the 5x step',
            }),
        ],
        [
            'a last step the drive was interrupted in before the run host could read its bar, while an invariant failed with no crossing unit in any step',
            {
                steps: [driven(0), driven(1), { ...driven(2, 100), endedAt: T + 4 * MINUTE + 20_000, dueUnits: 100 }],
                bars: [unreadAt(5)],
                invariants: [failed('resident_backlog_intact')],
            },
            limited({
                end: 'harness_limit',
                sustainedScale: 2,
                broke: { ...harnessAt(2, 'generator'), offeredPerSecond: 5 },
                reason: 'the drive ended during the 5x step',
            }),
        ],
        [
            'a bar that broke at a step whose late acknowledgements the generator did not count',
            { steps: [driven(0), driven(1), driven(2, 550)], bars: [brokeAt(5)] },
            {
                end: 'broke',
                sustainedScale: 2,
                broke: {
                    scale: 5,
                    offeredPerSecond: 550 / 120,
                    by: 'writer_cpu_under',
                    kind: 'bar',
                    at: iso(T),
                    part: 'db:cyclotron',
                },
                reason: 'writer_cpu_under broke at the 5x step',
            },
        ],
        [
            'a refusal that halted the drive early in its own step, which left that step short of its offers',
            {
                steps: [driven(0), driven(1), { ...driven(2, 10), endedAt: T + 4 * MINUTE + 5000, dueUnits: 25 }],
                stop: { index: 2, end: 'broke', reason: 'refused_at_intake went over its gate of 0 with 1 refused' },
                invariants: [failed('refused_at_intake', 'u-2-3')],
                gates: { refused_at_intake: 0 },
            },
            {
                end: 'broke',
                sustainedScale: 2,
                broke: {
                    scale: 5,
                    offeredPerSecond: 2,
                    by: 'refused_at_intake',
                    kind: 'gate',
                    at: iso(T + 4 * MINUTE),
                    part: null,
                },
                reason: 'refused_at_intake broke at the 5x step',
                stop: { failure: 'intake_refused', scale: 5, reason: 'refused_at_intake broke at the 5x step' },
            },
        ],
        [
            'a refusal that halted the drive early in a step whose runner lagged, which the runner outranks',
            {
                steps: [
                    driven(0),
                    driven(1),
                    { ...driven(2, 10), endedAt: T + 4 * MINUTE + 5000, dueUnits: 25, loopLagP99Ms: 900 },
                ],
                stop: { index: 2, end: 'broke', reason: 'refused_at_intake went over its gate of 0 with 1 refused' },
                invariants: [failed('refused_at_intake', 'u-2-3')],
                gates: { refused_at_intake: 0 },
            },
            limited({
                end: 'harness_limit',
                sustainedScale: 2,
                broke: { ...harnessAt(2, 'runner'), offeredPerSecond: 2 },
                reason: "the runner's event loop lagged 900 ms at p99 in the 5x step, over 250 ms",
            }),
        ],
        [
            'a refusal answered after its step ran its full length, which the generator offered short',
            {
                steps: [driven(0), driven(1), driven(2, 510)],
                stop: { index: 2, end: 'broke', reason: 'refused_at_intake went over its gate of 0 with 1 refused' },
                invariants: [failed('refused_at_intake', 'u-2-3')],
                gates: { refused_at_intake: 0 },
            },
            limited({
                end: 'harness_limit',
                sustainedScale: 2,
                broke: harnessAt(2, 'generator', 510),
                reason: 'the generator offered 510 of 600 units in the 5x step, under minOffered 0.9',
            }),
        ],
        [
            'every step held up to the last, but a job stayed unfinished past the convergence deadline',
            { convergence: { converged: false, unfinishedJobs: 1 } },
            {
                end: 'broke',
                sustainedScale: null,
                broke: undrained,
                reason: backlog,
                stop: { failure: 'backlog_undrained', scale: null, reason: backlog },
            },
        ],
        [
            'a bar that broke at a step, and a job that stayed unfinished past the convergence deadline',
            { bars: [brokeAt(5)], convergence: { converged: false, unfinishedJobs: 1 } },
            {
                end: 'broke',
                sustainedScale: 2,
                broke: barAt5,
                reason: 'writer_cpu_under broke at the 5x step',
                stop: { failure: 'backlog_undrained', scale: null, reason: backlog },
            },
        ],
        [
            'deliveries still unrecorded past the convergence deadline with no job unfinished, which count as lost',
            {
                convergence: { converged: false, unfinishedJobs: 0 },
                invariants: [failed('at_least_once', 'u-2-3')],
                rates: lostAt({ 2: 6 }),
            },
            {
                end: 'ceiling',
                sustainedScale: 5,
                reason: 'every step held up to the 5x ceiling',
                rates: lostAt({ 2: 6 }),
            },
        ],
        [
            'a step offered exactly its minOffered share, which is no shortfall',
            { minOffered: 0.14, steps: [driven(0), driven(1), { ...driven(2, 14), dueUnits: 100 }] },
            { end: 'ceiling', sustainedScale: 5, reason: 'every step held up to the 5x ceiling' },
        ],
        [
            'every step held up to the last',
            {},
            { end: 'ceiling', sustainedScale: 5, reason: 'every step held up to the 5x ceiling' },
        ],
        [
            'every step held up to the last, with a bar the stack has no source for',
            { bars: [{ ...held(), passed: false, unjudged: 'the local stack has no Aurora writer to read CPU from' }] },
            {
                end: 'ceiling',
                sustainedScale: 5,
                reason: 'every judged bar held up to the 5x ceiling; writer_cpu_under was not judged: the local stack has no Aurora writer to read CPU from',
            },
        ],
    ])('reads %s', (_story, evidence, expected) => {
        expect(
            rampOf({
                planned: STEPS,
                steps: STEPS_DRIVEN,
                minOffered: 0.9,
                stop: undefined,
                bars: [held()],
                invariants: [],
                gates: {},
                journal: JOURNAL,
                admissions: [],
                convergence: { converged: true, unfinishedJobs: 0 },
                ...evidence,
            })
        ).toEqual(expected)
    })

    const answered = (seq: number, unitId: string, status: number, fault?: string): TruthRecord => ({
        seq,
        at: iso(T + seq * 1000),
        kind: 'ses.send',
        unitId,
        actionId: 'email',
        status,
        ...(fault && { fault }),
        detail: {},
    })
    const DELIVERED = [
        answered(1, 'u-0-1', 200),
        answered(2, 'u-0-2', 200),
        answered(3, 'u-0-2', 200),
        answered(4, 'u-1-1', 400, 'ses.reject'),
        answered(5, 'u-1-3', 503),
        answered(6, 'u-1-3', 200),
    ]
    const STEP_JOURNAL = [unit(0, 1), unit(0, 2), unit(0, 3), unit(1, 1), unit(1, 2, false), unit(1, 3)]

    const UNSETTLED: StepRates[] = [
        {
            index: 0,
            scale: 1,
            expected: 3,
            lost: null,
            lossRate: null,
            sent: 2,
            duplicates: 1,
            duplicateRate: 0.5,
            refused: 0,
            refusedRate: 0,
        },
        {
            index: 1,
            scale: 2,
            expected: 2,
            lost: null,
            lossRate: null,
            sent: 1,
            duplicates: 0,
            duplicateRate: 0,
            refused: 1,
            refusedRate: 1 / 3,
        },
        {
            index: 2,
            scale: 5,
            expected: 0,
            lost: null,
            lossRate: null,
            sent: 0,
            duplicates: 0,
            duplicateRate: null,
            refused: 0,
            refusedRate: null,
        },
    ]

    it.each<[string, { lost: boolean; duplicates: boolean }, StepRates[], Pick<Convergence, 'unfinishedJobs'>?]>([
        [
            'counts per step the deliveries its accepted units expected, lost and duplicated',
            { lost: true, duplicates: true },
            [
                {
                    index: 0,
                    scale: 1,
                    expected: 3,
                    lost: 1,
                    lossRate: 1 / 3,
                    sent: 2,
                    duplicates: 1,
                    duplicateRate: 0.5,
                    refused: 0,
                    refusedRate: 0,
                },
                {
                    index: 1,
                    scale: 2,
                    expected: 2,
                    lost: 0,
                    lossRate: 0,
                    sent: 1,
                    duplicates: 0,
                    duplicateRate: 0,
                    refused: 1,
                    refusedRate: 1 / 3,
                },
                {
                    index: 2,
                    scale: 5,
                    expected: 0,
                    lost: 0,
                    lossRate: null,
                    sent: 0,
                    duplicates: 0,
                    duplicateRate: null,
                    refused: 0,
                    refusedRate: null,
                },
            ],
        ],
        [
            'leaves the losses unrecorded while a job stays unfinished, since its deliveries may only be late',
            { lost: true, duplicates: true },
            UNSETTLED,
            { unfinishedJobs: 1 },
        ],
        [
            'leaves the losses unrecorded when the judge could not read the job count at the deadline',
            { lost: true, duplicates: true },
            UNSETTLED,
            { unfinishedJobs: null },
        ],
        [
            'leaves the losses and duplicates of a card that judges neither unrecorded',
            { lost: false, duplicates: false },
            [
                {
                    index: 0,
                    scale: 1,
                    expected: 3,
                    lost: null,
                    lossRate: null,
                    sent: 2,
                    duplicates: null,
                    duplicateRate: null,
                    refused: 0,
                    refusedRate: 0,
                },
                {
                    index: 1,
                    scale: 2,
                    expected: 2,
                    lost: null,
                    lossRate: null,
                    sent: 1,
                    duplicates: null,
                    duplicateRate: null,
                    refused: 1,
                    refusedRate: 1 / 3,
                },
                {
                    index: 2,
                    scale: 5,
                    expected: 0,
                    lost: null,
                    lossRate: null,
                    sent: 0,
                    duplicates: null,
                    duplicateRate: null,
                    refused: 0,
                    refusedRate: null,
                },
            ],
        ],
    ])('%s', (_story, judged, expected, convergence = { unfinishedJobs: 0 }) => {
        expect(
            stepRatesOf(STEPS_DRIVEN, { journal: STEP_JOURNAL, truth: DELIVERED, fetchRetries: 3 }, judged, convergence)
        ).toEqual(expected)
    })

    it.each<[string, Partial<BarEvidence>]>([
        ['the final judge read the break', {}],
        [
            'the live judge read the break before the step counted its last acknowledgements',
            { settled: new Map([[1, [brokeAt(2)]]]) },
        ],
    ])('publishes one offered rate for a bar break, in the bar and in the ramp, when %s', (_story, changes) => {
        const steps = [driven(0), driven(1, 220), driven(2)]
        const bars = judgeBars([WRITER_CPU], {
            journal: JOURNAL,
            samples: [],
            host: [],
            drive: { startedAt: T, endedAt: T + 6 * MINUTE },
            steps: steps.map(({ scale, startedAt, endedAt, offeredUnits }) => ({
                scale,
                fromMs: startedAt - T,
                toMs: endedAt - T,
                offeredUnits,
            })),
            writerCpu: cpuByMinute([40, 40, 90, 90, 90, 90]),
            ...changes,
        })
        const ramp = rampOf({
            planned: STEPS,
            steps,
            minOffered: 0.9,
            stop: undefined,
            bars,
            invariants: [],
            gates: {},
            journal: JOURNAL,
            admissions: [],
            convergence: { converged: true, unfinishedJobs: 0 },
        })

        expect({ bar: bars[0].breakingPoint?.offeredPerSecond, ramp: ramp.broke?.offeredPerSecond }).toEqual({
            bar: 220 / 120,
            ramp: 220 / 120,
        })
    })
})
