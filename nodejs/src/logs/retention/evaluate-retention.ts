import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'
import type { LogRecord } from '~/logs/log-record-avro'

import { type FilterGroupNode, matchFilterGroup } from '../sampling/filter-group-match'

/**
 * Retention tiers a rule may assign. Kept in sync with `VALID_RETENTION_DAYS` in
 * `products/logs/backend/presentation/views/retention_api.py` (write-time validation) and
 * `RETENTION_USAGE_TIERS` in `logs-ingestion-consumer.ts`. Rows outside these tiers are
 * dropped at compile time so a hand-crafted or legacy row can't stamp an arbitrary value.
 */
export const VALID_RETENTION_DAYS = new Set([14, 30, 90])

export type CompiledRetentionRule = {
    id: string
    /** Selector for the logs this rule applies to. A rule with a null group matches nothing. */
    filterGroup: FilterGroupNode | null
    retentionDays: number
}

export type CompiledRetentionRuleSet = {
    rules: CompiledRetentionRule[]
}

/**
 * Incremented when a per-record retention evaluation throws. The record falls back to the
 * team default (fail-open) so a malformed rule can never break ingestion, but the counter
 * makes the silent failure observable.
 */
export const logsRetentionEvalErrorCounter = new Counter({
    name: 'logs_ingestion_retention_eval_error_total',
    help: 'Per-record retention evaluation threw an exception; record fell back to the team default (fail-open).',
    labelNames: ['team_id'],
})

/**
 * First matching rule (rules are pre-ordered by priority ASC, created_at ASC) sets the
 * record's retention. Returns null when no rule matches — the caller then applies the team
 * default. A rule with a null filterGroup matches nothing: never silently override retention
 * for all traffic (the API requires an explicit filter_group).
 */
export function evaluateRetentionDays(ruleSet: CompiledRetentionRuleSet | null, record: LogRecord): number | null {
    if (!ruleSet || ruleSet.rules.length === 0) {
        return null
    }
    for (const rule of ruleSet.rules) {
        if (rule.filterGroup && matchFilterGroup(rule.filterGroup, record)) {
            return rule.retentionDays
        }
    }
    return null
}

export function safeEvaluateRetentionDays(
    ruleSet: CompiledRetentionRuleSet | null,
    record: LogRecord,
    teamId: number
): number | null {
    try {
        return evaluateRetentionDays(ruleSet, record)
    } catch (err) {
        logsRetentionEvalErrorCounter.inc({ team_id: String(teamId) })
        logger.warn('[logs-retention] evaluateRetentionDays threw — falling back to team default', { teamId, err })
        return null
    }
}
