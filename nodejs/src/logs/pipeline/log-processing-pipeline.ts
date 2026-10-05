import type { LogRecord } from '~/logs/log-record-avro'

/**
 * Customer-sent content bytes of a row: body + attributes + event_name. The billing
 * pro-rate weight — deliberately NOT `bytes_uncompressed`, which includes per-row
 * denormalization overhead (resource attributes duplicated onto every row, server
 * uuid, id placeholders). That overhead is near-constant per row, so as a ratio
 * weight it would skew the pro-rate toward record-count weighting instead of
 * "share of what the customer sent".
 */
export function recordContentBytes(r: LogRecord): number {
    let total = Buffer.byteLength(r.body ?? '') + Buffer.byteLength(r.event_name ?? '')
    for (const [k, v] of Object.entries(r.attributes ?? {})) {
        total += Buffer.byteLength(k) + Buffer.byteLength(v ?? '')
    }
    return total
}

/**
 * Per-message drop accounting produced by `filter` stages (sampling drop rules, rate limits, hog
 * transformations). Fields mirror the billing pro-rate inputs the consumer already consumes: dropped
 * counts/bytes are attributed to the first matching rule UUID, and `contentBytes*` are the pro-rate
 * numerator/denominator. `droppedBy` records which stage removed the final surviving records so the
 * consumer can attribute an all-dropped message to sampling vs transformations.
 */
export type DropStats = {
    recordsDropped: number
    recordsDroppedByRuleId: Map<string, number>
    bytesDropped: number
    bytesDroppedByRuleId: Map<string, number>
    contentBytesDropped: number
    /**
     * Sum of customer-content bytes across the whole decoded batch, the pro-rate denominator. A stage
     * that measures after an earlier stage dropped rows sees fewer rows, so the first measurement wins.
     */
    contentBytesTotal: number
    recordsDroppedByStage: Map<string, number>
    /** Set by a filter stage when it removed records — the last such wins for all-dropped attribution. */
    droppedBy?: 'sampling' | 'transformations' | 'retention_expired'
}

export const EMPTY_DROP_STATS = (): DropStats => ({
    recordsDropped: 0,
    recordsDroppedByRuleId: new Map(),
    bytesDropped: 0,
    bytesDroppedByRuleId: new Map(),
    contentBytesDropped: 0,
    contentBytesTotal: 0,
    recordsDroppedByStage: new Map(),
})

/** Result of a `filter` stage: the surviving records plus what it dropped. */
export type FilterResult = { kept: LogRecord[]; stats: DropStats }

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
export type PipelineStage =
    | { kind: 'mutate'; name: string; run: (records: LogRecord[]) => Promise<void> | void }
    | {
          kind: 'filter'
          name: string
          run: (records: LogRecord[]) => Promise<FilterResult> | FilterResult
          /**
           * The pipeline measures the batch content total before any stage runs. Set this on a filter
           * that can run after another filter has dropped rows, because the rows it sees are no longer
           * the whole batch that the header bytes describe.
           */
          measuresBatchContentFirst?: boolean
      }

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
    if (stages.some((stage) => stage.kind === 'filter' && stage.measuresBatchContentFirst)) {
        stats.contentBytesTotal = records.reduce((sum, record) => sum + recordContentBytes(record), 0)
    }
    let working = records
    for (const stage of stages) {
        if (stage.kind === 'mutate') {
            await stage.run(working)
            continue
        }
        const { kept, stats: dropped } = await stage.run(working)
        stats.recordsDropped += dropped.recordsDropped
        stats.bytesDropped += dropped.bytesDropped
        stats.contentBytesDropped += dropped.contentBytesDropped
        if (stats.contentBytesTotal === 0 && dropped.contentBytesTotal > 0) {
            stats.contentBytesTotal = dropped.contentBytesTotal
        }
        if (dropped.recordsDropped > 0) {
            stats.recordsDroppedByStage.set(
                stage.name,
                (stats.recordsDroppedByStage.get(stage.name) ?? 0) + dropped.recordsDropped
            )
        }
        mergeByRuleId(stats.recordsDroppedByRuleId, dropped.recordsDroppedByRuleId)
        mergeByRuleId(stats.bytesDroppedByRuleId, dropped.bytesDroppedByRuleId)
        // Last filter that removed a record wins the all-dropped attribution — sampling runs before
        // hog transforms, so a message emptied by the transform is attributed to it, not sampling.
        if (dropped.droppedBy) {
            stats.droppedBy = dropped.droppedBy
        }
        working = kept
        if (working.length === 0) {
            break
        }
    }
    return { kept: working, stats }
}
