import { Counter } from 'prom-client'

import type { PipelineStage } from '~/logs/pipeline/log-processing-pipeline'

import { type CompiledRetentionRuleSet, safeEvaluateRetentionDays } from './evaluate-retention'

/**
 * Rows stamped with a per-row retention value, split by `matched`: `true` when a rule matched the
 * row, `false` when no rule matched and the team default was applied. A team whose rules are working
 * shows `matched="true"` traffic; a team seeing only `matched="false"` has rules that never match;
 * no traffic at all means the stage never ran (rule disabled, not fetched, or gating off).
 */
export const logsRetentionRowsStampedCounter = new Counter({
    name: 'logs_ingestion_retention_rows_stamped_total',
    help: 'Log rows stamped with a per-row retention value, labelled by whether a rule matched (matched=true) or the team default was applied (matched=false).',
    labelNames: ['team_id', 'matched'],
})

/**
 * Per-row retention `mutate` stage. Runs last in the pipeline (after sampling and hog transforms) so
 * it only stamps surviving records: `retention_days = firstMatchingRule ?? defaultRetentionDays`.
 * ClickHouse reads the per-row value and falls back to the batch `retention-days` header when it is
 * absent, so stamping the team default here keeps mixed and unmatched rows consistent.
 */
export function makeRetentionStage(
    ruleSet: CompiledRetentionRuleSet,
    teamId: number,
    defaultRetentionDays: number
): PipelineStage {
    return {
        kind: 'mutate',
        name: 'retention',
        run: (records) => {
            let matchedCount = 0
            for (const record of records) {
                const ruleValue = safeEvaluateRetentionDays(ruleSet, record, teamId)
                record.retention_days = ruleValue ?? defaultRetentionDays
                if (ruleValue !== null) {
                    matchedCount++
                }
            }
            // One increment per batch (not per record) to keep the hot path cheap.
            const teamLabel = String(teamId)
            if (matchedCount > 0) {
                logsRetentionRowsStampedCounter.inc({ team_id: teamLabel, matched: 'true' }, matchedCount)
            }
            const defaultCount = records.length - matchedCount
            if (defaultCount > 0) {
                logsRetentionRowsStampedCounter.inc({ team_id: teamLabel, matched: 'false' }, defaultCount)
            }
        },
    }
}
