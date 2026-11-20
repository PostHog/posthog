import {
    MessageFactory,
    Rng,
    TEAMS,
    baseScenario,
    finish,
    group,
    leaf,
    pathRule,
    setGeneratorClock,
    severityRule,
} from '../parity/parity-scenarios'
import type { ParityMessage, ParityScenario } from '../parity/parity-types'

export type BenchWorkloadOptions = {
    nowMs: number
    batches: number
    messagesPerBatch: number
    recordsPerMessage: number
}

export const DEFAULT_BENCH_OPTIONS: Omit<BenchWorkloadOptions, 'nowMs'> = {
    batches: 5,
    messagesPerBatch: 200,
    recordsPerMessage: 20,
}

// Buckets this large never bind, so a batch replayed many times does the same work every time.
const UNBOUNDED_LIMITER = {
    LOGS_LIMITER_BUCKET_SIZE_KB: 10_000_000,
    LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND: 10_000_000,
}

const [plain, , , both, attr] = TEAMS

async function batchesOf(
    rng: Rng,
    options: BenchWorkloadOptions,
    pickTeam: () => (typeof TEAMS)[number]
): Promise<ParityMessage[][]> {
    const f = new MessageFactory(rng)
    const batches: ParityMessage[][] = []
    for (let b = 0; b < options.batches; b++) {
        const batch: ParityMessage[] = []
        for (let m = 0; m < options.messagesPerBatch; m++) {
            batch.push(await f.logs(pickTeam(), options.recordsPerMessage))
        }
        batches.push(batch)
    }
    return batches
}

export async function buildBenchWorkloads(options: BenchWorkloadOptions): Promise<ParityScenario[]> {
    setGeneratorClock(options.nowMs)
    const workloads: ParityScenario[] = []

    {
        const s = baseScenario(
            'passthrough',
            'No settings or rules: the consumer forwards buffers undecoded.',
            UNBOUNDED_LIMITER
        )
        s.batches = await batchesOf(new Rng(101), options, () => plain)
        workloads.push(
            finish(
                s,
                s.batches.map(() => options.nowMs)
            )
        )
    }
    {
        const s = baseScenario('normalize', 'JSON body parse and PII scrub: decode, enrich, encode.', UNBOUNDED_LIMITER)
        s.batches = await batchesOf(new Rng(102), options, () => both)
        workloads.push(
            finish(
                s,
                s.batches.map(() => options.nowMs)
            )
        )
    }
    {
        const s = baseScenario('full', 'Every feature on for one team.', {
            ...UNBOUNDED_LIMITER,
            LOGS_SAMPLING_ENABLED_TEAMS: '*',
            LOGS_RETENTION_ENABLED_TEAMS: '*',
            LOGS_PATTERN_MASKING_ENABLED_TEAMS: '*',
            LOGS_METRICS_RULES_ENABLED_TEAMS: '*',
            LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS: '*',
            LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS: '*',
            LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS: '*',
            LOGS_BILLING_PRORATE_ENABLED: true,
        })
        s.teams = [{ ...attr, logs_settings: { ...attr.logs_settings, pii_scrub_logs: true } }]
        s.sampling_rules = {
            [attr.id]: [
                severityRule('sev', { DEBUG: { type: 'drop' }, INFO: { type: 'sample', rate: 0.8 } }),
                pathRule('path', { patterns: ['/healthz'], match_attribute_key: 'url.path' }),
            ],
        }
        s.retention_rules = {
            [attr.id]: {
                logs: [
                    {
                        id: 'errors',
                        config: {
                            retention_days: 90,
                            filter_group: group('AND', leaf('severity_text', 'exact', 'ERROR', 'log')),
                        },
                    },
                ],
            },
        }
        s.metric_rules = {
            [attr.id]: [
                {
                    id: 'by-level',
                    metric_name: 'by_level',
                    filter_group: null,
                    value_attribute: 'count',
                    group_by: ['severity_text', 'service_name'],
                },
            ],
        }
        s.batches = await batchesOf(new Rng(103), options, () => attr)
        workloads.push(
            finish(
                s,
                s.batches.map(() => options.nowMs)
            )
        )
    }
    {
        const s = baseScenario('mixed', 'A spread of teams and settings, like a production batch.', {
            ...UNBOUNDED_LIMITER,
            LOGS_SAMPLING_ENABLED_TEAMS: '102',
            LOGS_PATTERN_MASKING_ENABLED_TEAMS: '101,104',
            LOGS_RETENTION_ENABLED_TEAMS: '104',
        })
        s.sampling_rules = { 102: [severityRule('sev', { DEBUG: { type: 'drop' } })] }
        const rng = new Rng(104)
        s.batches = await batchesOf(rng, options, () => rng.pick(TEAMS))
        workloads.push(
            finish(
                s,
                s.batches.map(() => options.nowMs)
            )
        )
    }
    return workloads
}
