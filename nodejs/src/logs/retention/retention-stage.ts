import type { PipelineStage } from '~/logs/pipeline/log-processing-pipeline'

import { type CompiledRetentionRuleSet, safeEvaluateRetentionDays } from './evaluate-retention'

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
            for (const record of records) {
                record.retention_days = safeEvaluateRetentionDays(ruleSet, record, teamId) ?? defaultRetentionDays
            }
        },
    }
}
