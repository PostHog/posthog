import type { Step } from '../cards'
import { WEBHOOK_ACTION } from '../generator/traffic'
import type { TruthRecord } from '../provider-edge'
import type { IntakeAnswer, JournalEntry } from './judge'
import { MeasureEvidence, measure } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')
const MINUTE = 60_000
const HORIZON_SEQ = 100

const triggered = (unitId: string, step: number, offeredAtMs: number, answer: IntakeAnswer): JournalEntry => ({
    unitId,
    kind: 'webhook',
    teamId: 7,
    offeredAt: FROM + offeredAtMs,
    step,
    answer,
    expect: { deliveries: [WEBHOOK_ACTION] },
})

const delivered = (seq: number, unitId: string): TruthRecord => ({
    seq,
    at: new Date(FROM + 2 * MINUTE).toISOString(),
    kind: 'webhook',
    unitId,
    actionId: WEBHOOK_ACTION,
    status: 200,
    detail: {},
})

const ramp: Step[] = [
    { scale: 1, fromMs: 0, toMs: MINUTE },
    { scale: 5, fromMs: MINUTE, toMs: 2 * MINUTE },
]

const fastTriggers = Array.from({ length: 97 }, (_, i) =>
    triggered(`fast-${i}`, 0, 4000 + i, { accepted: true, attemptsMs: [25] })
)

const journal = [
    triggered('run-1', 0, 1000, { accepted: true, attemptsMs: [10] }),
    triggered('run-2', 0, 2000, { accepted: true, attemptsMs: [20] }),
    triggered('run-3', 0, 3000, { accepted: true, attemptsMs: [30] }),
    ...fastTriggers,
    triggered('run-late-1x', 0, MINUTE + 500, { accepted: false, status: 429, attemptsMs: [7] }),
    triggered('run-4', 1, MINUTE + 1000, { accepted: true, retries: 1, attemptsMs: [400, 5] }),
    triggered('run-5', 1, MINUTE + 2000, { accepted: false, status: 429, attemptsMs: [7] }),
    triggered('run-6', 1, MINUTE + 3000, { accepted: false, status: 503, retries: 2, attemptsMs: [60, 70, 80] }),
    triggered('run-7', 1, MINUTE + 4000, { accepted: false, transportError: 'ECONNRESET' }),
    { ...triggered('run-8', 1, MINUTE + 5000, { accepted: true }), kind: 'transactional' as const },
]

const evidence = (judged: Partial<MeasureEvidence> = {}): MeasureEvidence => ({
    journal,
    truth: [
        delivered(1, 'run-1'),
        delivered(2, 'run-2'),
        delivered(3, 'run-4'),
        ...fastTriggers.map(({ unitId }, i) => delivered(4 + i, unitId)),
        delivered(HORIZON_SEQ + 1, 'run-3'),
    ],
    horizonSeq: HORIZON_SEQ,
    truthFrom: 0,
    unobserved: [],
    fetchRetries: 3,
    samples: [],
    missed: [],
    host: [],
    writer: [],
    queue: [],
    sampledFrom: FROM,
    drive: { startedAt: FROM, endedAt: FROM + 2 * MINUTE },
    steps: ramp,
    timeline: [],
    ...judged,
})

const rowsOf = (judged?: Partial<MeasureEvidence>): Record<string, unknown> =>
    Object.fromEntries(
        measure(
            [
                { name: 'webhook_trigger_answer_ms', params: {} },
                { name: 'webhook_trigger_outcomes', params: {} },
            ],
            evidence(judged)
        ).map(({ name, key, value }) => [`${name}.${key}`, value])
    )

describe('workflow webhook triggers per ramp step', () => {
    it('times every answered attempt and counts each trigger by its final answer, in the step that offered it', () => {
        expect(rowsOf()).toEqual({
            'webhook_trigger_answer_ms.p50_1x': 25,
            'webhook_trigger_answer_ms.p99_1x': 25,
            'webhook_trigger_answer_ms.p50_5x': 60,
            'webhook_trigger_answer_ms.p99_5x': 400,
            'webhook_trigger_outcomes.offered_1x': 101,
            'webhook_trigger_outcomes.accepted_1x': 100,
            'webhook_trigger_outcomes.rejected_1x': 1,
            'webhook_trigger_outcomes.errors_1x': 0,
            'webhook_trigger_outcomes.lost_1x': 1,
            'webhook_trigger_outcomes.offered_5x': 4,
            'webhook_trigger_outcomes.accepted_5x': 1,
            'webhook_trigger_outcomes.rejected_5x': 1,
            'webhook_trigger_outcomes.errors_5x': 2,
            'webhook_trigger_outcomes.lost_5x': 0,
        })
    })

    it('marks the answer times of a step incomplete when an attempt in it got no answer', () => {
        const rows = measure([{ name: 'webhook_trigger_answer_ms', params: {} }], evidence())

        expect(rows.map(({ key, incomplete }) => [key, incomplete ?? false])).toEqual([
            ['p50_1x', false],
            ['p99_1x', false],
            ['p50_5x', true],
            ['p99_5x', true],
        ])
    })

    it.each<[string, IntakeAnswer, Record<string, unknown>]>([
        [
            'leaves a step untimed when no attempt in it got an answer',
            { accepted: false, transportError: 'ECONNRESET' },
            { value: null, censored: true },
        ],
        [
            'keeps the 503 timing when the retry after it timed out',
            { accepted: false, transportError: 'TimeoutError', retries: 1, attemptsMs: [60] },
            { value: 60 },
        ],
    ])('%s, and marks the step incomplete', (_, answer, timed) => {
        const rows = measure(
            [{ name: 'webhook_trigger_answer_ms', params: {} }],
            evidence({ journal: [triggered('run-7', 0, 1000, answer)] })
        )

        expect(rows.filter(({ key }) => key?.endsWith('_1x'))).toEqual([
            expect.objectContaining({ key: 'p50_1x', ...timed, incomplete: true }),
            expect.objectContaining({ key: 'p99_1x', ...timed, incomplete: true }),
        ])
    })

    it('marks every webhook row of an interrupted run incomplete', () => {
        const rows = measure(
            [
                { name: 'webhook_trigger_answer_ms', params: {} },
                { name: 'webhook_trigger_outcomes', params: {} },
            ],
            evidence({ interrupted: true })
        )

        expect(rows.filter(({ incomplete }) => !incomplete).map(({ name, key }) => `${name}.${key}`)).toEqual([])
    })

    it.each<[string, Partial<MeasureEvidence>, string]>([
        ['the truth could not be read', { unread: 'edge unreachable' }, 'edge unreachable'],
        ['the run reached no recovery horizon', { horizonSeq: undefined }, 'no recovery horizon'],
        [
            'the run reached no recovery horizon and its last truth read failed',
            { horizonSeq: undefined, unread: 'the run was stopped' },
            'no recovery horizon',
        ],
        [
            'the truth skips a seq',
            { truth: evidence().truth.filter(({ seq }) => seq !== 5) },
            'the truth skips from seq 4 to 6',
        ],
        ['the truth never settled', { unsettled: 'the edge kept accepting sends' }, 'the edge kept accepting sends'],
        [
            'a valve went unobserved',
            { unobserved: ['role.kill on cdp-intake-workflow-webhook was not observed'] },
            'role.kill on cdp-intake-workflow-webhook was not observed',
        ],
        [
            'the edge accepted a delivery the journal never recorded',
            { truth: [...evidence().truth, delivered(HORIZON_SEQ + 2, 'run-99')] },
            'the journal is incomplete',
        ],
    ])('leaves the lost count unmeasured when %s', (_, judged, reason) => {
        const rows = measure([{ name: 'webhook_trigger_outcomes', params: {} }], evidence(judged))

        expect(rows.filter(({ key }) => key?.startsWith('lost'))).toEqual([
            expect.objectContaining({
                key: 'lost_1x',
                value: null,
                censored: true,
                unmeasured: expect.stringContaining(reason),
            }),
            expect.objectContaining({ key: 'lost_5x', value: null, censored: true }),
        ])
    })
})
