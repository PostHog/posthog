import type { Step } from '../cards'
import { WEBHOOK_ACTION } from '../generator/traffic'
import type { TruthRecord } from '../provider-edge'
import type { IntakeAnswer, JournalEntry } from './judge'
import { MeasureEvidence, measure } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')
const MINUTE = 60_000

const triggered = (unitId: string, offeredAtMs: number, answer: IntakeAnswer): JournalEntry => ({
    unitId,
    kind: 'webhook',
    teamId: 7,
    offeredAt: FROM + offeredAtMs,
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
    { scale: 10, fromMs: 2 * MINUTE, toMs: 3 * MINUTE },
]

const journal = [
    triggered('run-1', 1000, { accepted: true, attemptsMs: [10] }),
    triggered('run-2', 2000, { accepted: true, attemptsMs: [20] }),
    triggered('run-3', 3000, { accepted: true, attemptsMs: [30] }),
    triggered('run-4', MINUTE + 1000, { accepted: true, retries: 1, attemptsMs: [400, 5] }),
    triggered('run-5', MINUTE + 2000, { accepted: false, status: 429, attemptsMs: [7] }),
    triggered('run-6', MINUTE + 3000, { accepted: false, status: 503, retries: 2, attemptsMs: [60, 70, 80] }),
    triggered('run-7', MINUTE + 4000, { accepted: false, transportError: 'ECONNRESET' }),
    { ...triggered('run-8', MINUTE + 5000, { accepted: true }), kind: 'transactional' as const },
]

const evidence = (judged: Partial<MeasureEvidence> = {}): MeasureEvidence => ({
    journal,
    truth: [delivered(1, 'run-1'), delivered(2, 'run-2'), delivered(3, 'run-4')],
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
    it('times every answered attempt and counts each trigger by its final answer, per step the drive reached', () => {
        expect(rowsOf()).toEqual({
            'webhook_trigger_answer_ms.p50_1x': 20,
            'webhook_trigger_answer_ms.p99_1x': 30,
            'webhook_trigger_answer_ms.p50_5x': 60,
            'webhook_trigger_answer_ms.p99_5x': 400,
            'webhook_trigger_outcomes.offered_1x': 3,
            'webhook_trigger_outcomes.accepted_1x': 3,
            'webhook_trigger_outcomes.rejected_1x': 0,
            'webhook_trigger_outcomes.errors_1x': 0,
            'webhook_trigger_outcomes.lost_1x': 1,
            'webhook_trigger_outcomes.offered_5x': 4,
            'webhook_trigger_outcomes.accepted_5x': 1,
            'webhook_trigger_outcomes.rejected_5x': 1,
            'webhook_trigger_outcomes.errors_5x': 2,
            'webhook_trigger_outcomes.lost_5x': 0,
        })
    })

    it('leaves the lost count unmeasured when the truth could not be read, and a step with no answer untimed', () => {
        const rows = measure(
            [
                { name: 'webhook_trigger_answer_ms', params: {} },
                { name: 'webhook_trigger_outcomes', params: {} },
            ],
            evidence({
                journal: [triggered('run-7', 1000, { accepted: false, transportError: 'ECONNRESET' })],
                unread: 'edge unreachable',
            })
        )

        expect(rows.filter(({ key }) => key?.startsWith('p') || key?.startsWith('lost'))).toEqual([
            expect.objectContaining({ key: 'p50_1x', value: null, censored: true }),
            expect.objectContaining({ key: 'p99_1x', value: null, censored: true }),
            expect.objectContaining({ key: 'p50_5x', value: null, censored: true }),
            expect.objectContaining({ key: 'p99_5x', value: null, censored: true }),
            expect.objectContaining({
                key: 'lost_1x',
                value: null,
                censored: true,
                unmeasured: expect.stringContaining('edge unreachable'),
            }),
            expect.objectContaining({ key: 'lost_5x', value: null, censored: true }),
        ])
    })
})
