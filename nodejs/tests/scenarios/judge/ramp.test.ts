import type { Named, Step } from '../cards'
import type { DrivenStep, StepWindow } from '../generator/generator'
import { type BarEvidence, type BarResult, type CpuPoint, judgeBars } from './bars'
import type { InvariantResult, JournalEntry } from './judge'
import { type MetricSample, SCRAPE_GAP_MS } from './measurements'
import { Broke, LiveRamp, Ramp, RampEvidence, RampStop, rampOf, watchRamp } from './ramp'

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
            'stops at a step whose bar broke, naming the part it measures and the rate the generator reached',
            {},
            1,
            UNITS_PER_STEP[1],
            {
                advance: false,
                stop: {
                    index: 1,
                    end: 'broke',
                    reason: 'writer_cpu_under broke at the 2x step',
                    broke: {
                        scale: 2,
                        offeredPerSecond: 2,
                        by: 'writer_cpu_under',
                        kind: 'bar',
                        at: iso(T + 2 * MINUTE),
                        part: 'db:cyclotron',
                    },
                },
            },
        ],
        [
            'keeps a broken bar as the break when a sibling bar could not be read in the same step',
            { bars: [WRITER_CPU, PICKUP] },
            1,
            UNITS_PER_STEP[1],
            {
                advance: false,
                stop: expect.objectContaining({
                    end: 'broke',
                    broke: expect.objectContaining({ by: 'writer_cpu_under' }),
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
            { writerCpu: () => Promise.reject(new Error('socket hang up')) },
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
    ])('%s', async (_story, overrides, index, offered, expected) => {
        jest.setSystemTime(windowOf(index).endedAt)
        const watch = watchRamp(live(overrides), NEVER)

        const verdict = watch.gate(windowOf(index), () => offered)
        await jest.advanceTimersByTimeAsync(SCRAPE_GAP_MS)
        await verdict

        expect({ advance: !watch.halt.aborted, stop: watch.stopped() }).toEqual(expected)
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
    const harnessAt = (index: number, by: 'generator' | 'run_host', offeredUnits = UNITS_PER_STEP[index]): Broke => ({
        scale: STEPS[index].scale,
        offeredPerSecond: offeredUnits / 120,
        by,
        kind: 'harness',
        at: iso(T + STEPS[index].fromMs),
        part: null,
    })
    const liveBreak: Broke = {
        scale: 2,
        offeredPerSecond: 2,
        by: 'writer_cpu_under',
        kind: 'bar',
        at: iso(T + 2 * MINUTE),
        part: 'db:cyclotron',
    }

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
            'an invariant whose crossing unit sits below the step where a bar broke',
            { bars: [brokeAt(5)], invariants: [failed('at_least_once', 'u-1-7')] },
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
                reason: 'at_least_once broke at the 2x step',
            },
        ],
        [
            'a gated invariant that failed at the first step',
            { invariants: [failed('duplicate_sends', 'u-0-3')], gates: { duplicate_sends: 0 } },
            {
                end: 'broke',
                sustainedScale: null,
                broke: { scale: 1, offeredPerSecond: 1, by: 'duplicate_sends', kind: 'gate', at: iso(T), part: null },
                reason: 'duplicate_sends broke at the 1x step',
            },
        ],
        [
            'a failed invariant with no crossing unit in any step',
            { invariants: [failed('resident_backlog_intact')] },
            {
                end: 'broke',
                sustainedScale: null,
                broke: {
                    scale: null,
                    offeredPerSecond: null,
                    by: 'resident_backlog_intact',
                    kind: 'invariant',
                    at: null,
                    part: null,
                },
                reason: 'resident_backlog_intact failed, and the unit that crossed its gate falls in no step',
            },
        ],
        [
            'a live bar break that the final judge could not read again',
            {
                steps: STEPS_DRIVEN.slice(0, 2),
                bars: [unreadAt(2)],
                stop: { index: 1, end: 'broke', reason: 'writer_cpu_under broke at the 2x step', broke: liveBreak },
            },
            { end: 'broke', sustainedScale: 1, broke: liveBreak, reason: 'writer_cpu_under broke at the 2x step' },
        ],
        [
            'a live bar break whose step counted more acknowledgements after the live judge read it',
            {
                steps: STEPS_DRIVEN.slice(0, 2),
                stop: {
                    index: 1,
                    end: 'broke',
                    reason: 'writer_cpu_under broke at the 2x step',
                    broke: { ...liveBreak, offeredPerSecond: 1.5 },
                },
            },
            { end: 'broke', sustainedScale: 1, broke: liveBreak, reason: 'writer_cpu_under broke at the 2x step' },
        ],
        [
            'a last step the generator offered short, which is no ceiling',
            { steps: [driven(0), driven(1), driven(2, 510)] },
            {
                end: 'harness_limit',
                sustainedScale: 2,
                broke: harnessAt(2, 'generator', 510),
                reason: 'the generator offered 510 of 600 units in the 5x step, under minOffered 0.9',
            },
        ],
        [
            'a step offered short below the step where a bar broke',
            { steps: [driven(0), driven(1, 200), driven(2)], bars: [brokeAt(5)] },
            {
                end: 'harness_limit',
                sustainedScale: 1,
                broke: harnessAt(1, 'generator', 200),
                reason: 'the generator offered 200 of 240 units in the 2x step, under minOffered 0.9',
            },
        ],
        [
            'a last step whose bar the run host could not read',
            { bars: [unreadAt(5)] },
            {
                end: 'harness_limit',
                sustainedScale: 2,
                broke: harnessAt(2, 'run_host'),
                reason: 'writer_cpu_under was not judged: no writer CPU reading in the 5x step',
            },
        ],
        [
            'a first step whose schedule held no units, which sustains nothing',
            { steps: [{ ...driven(0, 0), dueUnits: 0 }, driven(1), driven(2)], bars: [brokeAt(5)] },
            {
                end: 'harness_limit',
                sustainedScale: null,
                broke: harnessAt(0, 'generator', 0),
                reason: 'the generator had no units to offer in the 1x step',
            },
        ],
        [
            'a baseline that failed its load admission, so no scale was sustained',
            {
                admissions: [{ name: 'load', passed: false, reason: 'hogflow claims ran at 1/s, under 5/s' }],
            },
            {
                end: 'harness_limit',
                sustainedScale: null,
                broke: harnessAt(0, 'generator'),
                reason: 'the load admission failed at the 1x step: hogflow claims ran at 1/s, under 5/s',
            },
        ],
        [
            'a last step the drive was interrupted in, which is no ceiling',
            { steps: [driven(0), driven(1), { ...driven(2, 100), endedAt: T + 4 * MINUTE + 20_000, dueUnits: 100 }] },
            {
                end: 'harness_limit',
                sustainedScale: 2,
                broke: { ...harnessAt(2, 'generator'), offeredPerSecond: 5 },
                reason: 'the drive ended during the 5x step',
            },
        ],
        [
            'a last step the drive was interrupted in before the run host could read its bar',
            {
                steps: [driven(0), driven(1), { ...driven(2, 100), endedAt: T + 4 * MINUTE + 20_000, dueUnits: 100 }],
                bars: [unreadAt(5)],
            },
            {
                end: 'harness_limit',
                sustainedScale: 2,
                broke: { ...harnessAt(2, 'generator'), offeredPerSecond: 5 },
                reason: 'the drive ended during the 5x step',
            },
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
            'every step held up to the last',
            {},
            { end: 'ceiling', sustainedScale: 5, reason: 'every step held up to the 5x ceiling' },
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
                ...evidence,
            })
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
        })

        expect({ bar: bars[0].breakingPoint?.offeredPerSecond, ramp: ramp.broke?.offeredPerSecond }).toEqual({
            bar: 220 / 120,
            ramp: 220 / 120,
        })
    })
})
