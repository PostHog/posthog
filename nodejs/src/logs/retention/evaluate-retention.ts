import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'
import type { LogRecord } from '~/logs/log-record-avro'

import { type FilterGroupNode, matchFilterGroup } from '../sampling/filter-group-match'

/**
 * Kept in sync with `logs_retention_days_error` in `posthog/models/team/logs_retention.py`. Rows
 * outside this shape are dropped at compile time so a hand-crafted or legacy row can't stamp an arbitrary value.
 */
export const DEFAULT_RETENTION_DAYS = 14
export const RETENTION_MONTH_DAYS = 30
export const MAX_RETENTION_DAYS = RETENTION_MONTH_DAYS * 120

export function isValidRetentionDays(days: number): boolean {
    if (!Number.isInteger(days)) {
        return false
    }
    if (days === DEFAULT_RETENTION_DAYS) {
        return true
    }
    return days > 0 && days <= MAX_RETENTION_DAYS && days % RETENTION_MONTH_DAYS === 0
}

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
