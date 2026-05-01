import { createHash } from 'crypto'

import type { LogRecord } from '../log-record-avro'

export const SAMPLING_DECISION_KEEP = 'keep' as const
export const SAMPLING_DECISION_DROP = 'drop' as const
export const SAMPLING_DECISION_SAMPLE_KEPT = 'sample_kept' as const
export const SAMPLING_DECISION_SAMPLE_DROPPED = 'sample_dropped' as const

export type SamplingDecision =
    | typeof SAMPLING_DECISION_KEEP
    | typeof SAMPLING_DECISION_DROP
    | typeof SAMPLING_DECISION_SAMPLE_KEPT
    | typeof SAMPLING_DECISION_SAMPLE_DROPPED

export type SeverityAction = { type: 'keep' } | { type: 'drop' } | { type: 'sample'; rate: number }

export type CompiledSamplingRule = {
    id: string
    ruleType: 'severity_sampling' | 'path_drop' | 'rate_limit'
    scopeService: string | null
    pathRegex: RegExp | null
    pathDropPatterns: RegExp[] | null
    severityActions: [SeverityAction, SeverityAction, SeverityAction, SeverityAction]
    alwaysKeep: {
        statusGte: number | null
        latencyMsGt: number | null
        attributePredicates: { key: string; op: string; value?: string }[]
    } | null
}

export type CompiledRuleSet = {
    rules: CompiledSamplingRule[]
}

const SEV_ORD_DEBUG = 0
const SEV_ORD_INFO = 1
const SEV_ORD_WARN = 2
const SEV_ORD_ERROR = 3

export function severityOrdinalFromRecord(record: LogRecord): number {
    const t = (record.severity_text || '').toLowerCase()
    if (t === 'trace' || t === 'debug') {
        return SEV_ORD_DEBUG
    }
    if (t === 'info') {
        return SEV_ORD_INFO
    }
    if (t === 'warn' || t === 'warning') {
        return SEV_ORD_WARN
    }
    if (t === 'error' || t === 'fatal') {
        return SEV_ORD_ERROR
    }
    const n = record.severity_number
    if (n == null) {
        return SEV_ORD_INFO
    }
    if (n >= 17) {
        return SEV_ORD_ERROR
    }
    if (n >= 13) {
        return SEV_ORD_WARN
    }
    if (n >= 9) {
        return SEV_ORD_INFO
    }
    return SEV_ORD_DEBUG
}

function hash01FromTraceId(traceId: Buffer | null): number {
    if (!traceId || traceId.length === 0) {
        return Math.random()
    }
    const h = createHash('sha256').update(traceId).digest()
    return h.readUInt32BE(0) / 0xffffffff
}

function getAttribute(record: LogRecord, key: string): string | undefined {
    const a = record.attributes
    if (!a) {
        return undefined
    }
    return a[key]
}

function pathForMatching(record: LogRecord): string {
    const candidates = ['url.path', 'http.path', 'http.route', 'path']
    for (const k of candidates) {
        const v = getAttribute(record, k)
        if (v) {
            return v
        }
    }
    return ''
}

function alwaysKeepMatches(rule: CompiledSamplingRule, record: LogRecord): boolean {
    const ak = rule.alwaysKeep
    if (!ak) {
        return false
    }
    if (ak.statusGte != null) {
        const codeStr = getAttribute(record, 'http.status_code') || getAttribute(record, 'http.response.status_code')
        const code = codeStr ? parseInt(codeStr, 10) : NaN
        if (!Number.isNaN(code) && code >= ak.statusGte) {
            return true
        }
    }
    if (ak.latencyMsGt != null) {
        const latStr = getAttribute(record, 'http.server.duration_ms') || getAttribute(record, 'duration_ms')
        const lat = latStr ? parseFloat(latStr) : NaN
        if (!Number.isNaN(lat) && lat > ak.latencyMsGt) {
            return true
        }
    }
    for (const p of ak.attributePredicates) {
        const v = getAttribute(record, p.key)
        if (p.op === 'exists' && v !== undefined) {
            return true
        }
        if (p.op === 'eq' && p.value !== undefined && v === p.value) {
            return true
        }
        if (p.op === 'ne' && p.value !== undefined && v !== undefined && v !== p.value) {
            return true
        }
    }
    return false
}

function matchesScope(rule: CompiledSamplingRule, record: LogRecord): boolean {
    if (rule.scopeService != null && rule.scopeService !== '') {
        const sn = record.service_name || ''
        if (sn !== rule.scopeService) {
            return false
        }
    }
    if (rule.pathRegex) {
        const p = pathForMatching(record)
        if (!rule.pathRegex.test(p)) {
            return false
        }
    }
    return true
}

export type EvaluateResult = {
    decision: SamplingDecision
    /** UUID of the first matching rule, if any */
    ruleId: string | null
}

export function evaluateLogRecord(teamRuleSet: CompiledRuleSet | null, record: LogRecord): EvaluateResult {
    if (!teamRuleSet || teamRuleSet.rules.length === 0) {
        return { decision: SAMPLING_DECISION_KEEP, ruleId: null }
    }
    const ord = severityOrdinalFromRecord(record)
    for (const rule of teamRuleSet.rules) {
        if (!matchesScope(rule, record)) {
            continue
        }
        if (alwaysKeepMatches(rule, record)) {
            return { decision: SAMPLING_DECISION_KEEP, ruleId: rule.id }
        }
        if (rule.ruleType === 'path_drop') {
            if (!rule.pathDropPatterns || rule.pathDropPatterns.length === 0) {
                continue
            }
            const p = pathForMatching(record)
            for (const rx of rule.pathDropPatterns) {
                if (rx.test(p)) {
                    return { decision: SAMPLING_DECISION_DROP, ruleId: rule.id }
                }
            }
            continue
        }
        if (rule.ruleType === 'severity_sampling') {
            const action = rule.severityActions[ord]
            if (action.type === 'keep') {
                return { decision: SAMPLING_DECISION_KEEP, ruleId: rule.id }
            }
            if (action.type === 'drop') {
                return { decision: SAMPLING_DECISION_DROP, ruleId: rule.id }
            }
            const u = hash01FromTraceId(record.trace_id)
            if (u < action.rate) {
                return { decision: SAMPLING_DECISION_SAMPLE_KEPT, ruleId: rule.id }
            }
            return { decision: SAMPLING_DECISION_SAMPLE_DROPPED, ruleId: rule.id }
        }
        if (rule.ruleType === 'rate_limit') {
            continue
        }
    }
    return { decision: SAMPLING_DECISION_KEEP, ruleId: null }
}
