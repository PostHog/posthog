import type { LogRecord } from '~/logs/log-record-avro'

function stringBytes(value: string | null | undefined): number {
    return value ? Buffer.byteLength(value) : 0
}

function mapBytes(map: Record<string, string> | null | undefined): number {
    let total = 0
    for (const [k, v] of Object.entries(map ?? {})) {
        total += Buffer.byteLength(k) + stringBytes(v)
    }
    return total
}

function resourceKey(map: Record<string, string> | null | undefined): string {
    return JSON.stringify(Object.entries(map ?? {}).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
}

/**
 * Every sender-controlled field counts, or a surviving row can hold its content where it weighs
 * nothing and a dropped neighbor refunds the whole batch. Resource and scope bytes are split across
 * the rows that share them, because a per-row count lets a sender inflate the rows it expects to drop.
 */
export function measureContentWeights(records: LogRecord[]): Map<LogRecord, number> {
    const rowsByResource = new Map<string, number>()
    const rowsByScope = new Map<string, number>()
    const keys = records.map((record) => {
        const resource = resourceKey(record.resource_attributes)
        const scope = JSON.stringify([resource, record.instrumentation_scope ?? ''])
        rowsByResource.set(resource, (rowsByResource.get(resource) ?? 0) + 1)
        rowsByScope.set(scope, (rowsByScope.get(scope) ?? 0) + 1)
        return { resource, scope }
    })

    const weights = new Map<LogRecord, number>()
    records.forEach((record, i) => {
        const { resource, scope } = keys[i]
        weights.set(
            record,
            stringBytes(record.body) +
                stringBytes(record.event_name) +
                stringBytes(record.severity_text) +
                mapBytes(record.attributes) +
                mapBytes(record.resource_attributes) / rowsByResource.get(resource)! +
                stringBytes(record.instrumentation_scope) / rowsByScope.get(scope)!
        )
    })
    return weights
}

export type StageDropStats = {
    recordsDropped: number
    recordsDroppedByRuleId: Map<string, number>
    bytesDropped: number
    bytesDroppedByRuleId: Map<string, number>
    contentBytesDropped: number
}

export const EMPTY_STAGE_DROP_STATS = (): StageDropStats => ({
    recordsDropped: 0,
    recordsDroppedByRuleId: new Map(),
    bytesDropped: 0,
    bytesDroppedByRuleId: new Map(),
    contentBytesDropped: 0,
})

/**
 * Per-message drop accounting: the stages' reports summed, plus what the pipeline measures itself.
 * `contentBytesTotal` is the billing pro-rate denominator, measured over the whole decoded batch
 * before any stage runs, because the header bytes it is applied to describe the whole batch.
 * `droppedBy` names the last stage that removed records, which attributes an all-dropped message.
 */
export type DropStats = StageDropStats & {
    contentBytesTotal: number
    recordsDroppedByStage: Map<string, number>
    droppedBy?: string
}

export const EMPTY_DROP_STATS = (): DropStats => ({
    ...EMPTY_STAGE_DROP_STATS(),
    contentBytesTotal: 0,
    recordsDroppedByStage: new Map(),
})

/** Result of a `filter` stage: the surviving records plus what it dropped. */
export type FilterResult = { kept: LogRecord[]; stats: StageDropStats }

/**
 * Content weights fixed before any stage runs. A drop credit must use them, never the row's current
 * size: a hog transformation can grow a row before a later stage drops it, and crediting the grown
 * size would let a team buy back more of the batch than it sent.
 */
export type BatchContext = {
    contentBytesTotal: number
    contentBytesOf: (record: LogRecord) => number
}

/**
 * A stage in the decode → transform → encode pipeline. Stages run in list order over one decode:
 * - `mutate` edits records in place (per-row retention stamping).
 * - `filter` removes records and reports what it dropped (sampling drop rules, rate limits, hog
 *   transformations that drop).
 *
 * PII scrub / JSON enrich run as a fixed normalize step before the stages (see
 * `processLogMessageBuffer`), and metric-rule extraction runs as the `onRecordsDecoded` visitor
 * between normalize and the stages — both must see every record post-scrub and pre-drop.
 */
export type MutateStage = { kind: 'mutate'; name: string; run: (records: LogRecord[]) => Promise<void> | void }
export type FilterStage = {
    kind: 'filter'
    name: string
    run: (records: LogRecord[], batch: BatchContext) => Promise<FilterResult> | FilterResult
}
export type PipelineStage = MutateStage | FilterStage

function mergeByRuleId(into: Map<string, number>, from: Map<string, number>): void {
    for (const [ruleId, n] of from) {
        into.set(ruleId, (into.get(ruleId) ?? 0) + n)
    }
}

/**
 * Runs the stages over the decoded records in order, mutating `records` in place for `mutate`/`visit`
 * and replacing the working set on each `filter`. Returns the surviving records and the aggregated
 * drop accounting. Stops early once every record has been dropped so later stages don't run on an
 * empty set (and `droppedBy` reflects the stage that emptied it).
 */
export async function runPipelineStages(
    records: LogRecord[],
    stages: PipelineStage[]
): Promise<{ kept: LogRecord[]; stats: DropStats }> {
    const stats = EMPTY_DROP_STATS()
    const weights = stages.some((stage) => stage.kind === 'filter')
        ? measureContentWeights(records)
        : new Map<LogRecord, number>()
    for (const weight of weights.values()) {
        stats.contentBytesTotal += weight
    }
    const batch: BatchContext = {
        contentBytesTotal: stats.contentBytesTotal,
        contentBytesOf: (record) => weights.get(record) ?? 0,
    }
    let working = records
    for (const stage of stages) {
        if (stage.kind === 'mutate') {
            await stage.run(working)
            continue
        }
        // A hog transform removes rows from the array it is given, so count before the stage runs.
        const before = working.length
        const { kept, stats: dropped } = await stage.run(working, batch)
        stats.recordsDropped += dropped.recordsDropped
        stats.bytesDropped += dropped.bytesDropped
        stats.contentBytesDropped += dropped.contentBytesDropped
        mergeByRuleId(stats.recordsDroppedByRuleId, dropped.recordsDroppedByRuleId)
        mergeByRuleId(stats.bytesDroppedByRuleId, dropped.bytesDroppedByRuleId)
        const removed = before - kept.length
        if (removed > 0) {
            stats.recordsDroppedByStage.set(stage.name, (stats.recordsDroppedByStage.get(stage.name) ?? 0) + removed)
            // Last filter that removed a record wins the all-dropped attribution — sampling runs before
            // hog transforms, so a message emptied by the transform is attributed to it, not sampling.
            stats.droppedBy = stage.name
        }
        working = kept
        if (working.length === 0) {
            break
        }
    }
    return { kept: working, stats }
}
