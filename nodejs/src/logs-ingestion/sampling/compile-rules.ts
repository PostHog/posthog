import type { CompiledRuleSet, CompiledSamplingRule, SeverityAction } from './evaluate'

export type SamplingRuleRow = {
    id: string
    rule_type: string
    scope_service: string | null
    scope_path_pattern: string | null
    scope_attribute_filters: unknown
    config: Record<string, unknown>
    /** Row version from DB; used by cache watermark only, ignored by compileRuleSet. */
    version?: number
}

const defaultSeverityActions = (): [SeverityAction, SeverityAction, SeverityAction, SeverityAction] => [
    { type: 'keep' },
    { type: 'keep' },
    { type: 'keep' },
    { type: 'keep' },
]

function parseSeverityActions(raw: unknown): [SeverityAction, SeverityAction, SeverityAction, SeverityAction] {
    const out = defaultSeverityActions()
    if (!raw || typeof raw !== 'object') {
        return out
    }
    const actions = (raw as { actions?: Record<string, unknown> }).actions
    if (!actions || typeof actions !== 'object') {
        return out
    }
    const levels = ['DEBUG', 'INFO', 'WARN', 'ERROR'] as const
    for (let i = 0; i < levels.length; i++) {
        const key = levels[i]
        const a = actions[key] as Record<string, unknown> | undefined
        if (!a || typeof a.type !== 'string') {
            continue
        }
        if (a.type === 'drop') {
            out[i] = { type: 'drop' }
        } else if (a.type === 'sample' && typeof a.rate === 'number') {
            out[i] = { type: 'sample', rate: Math.max(0, Math.min(1, a.rate)) }
        } else {
            out[i] = { type: 'keep' }
        }
    }
    return out
}

const MAX_LOGS_PER_SECOND = 1_000_000
const MAX_BURST_LOGS = 60_000_000

function parseRateLimitFromConfig(
    config: Record<string, unknown>
): { refillPerSecond: number; poolMax: number } | null {
    const lps = config.logs_per_second
    if (typeof lps !== 'number' || !Number.isFinite(lps) || lps < 1 || lps > MAX_LOGS_PER_SECOND) {
        return null
    }
    const refill = Math.floor(lps)
    const burstRaw = config.burst_logs
    let poolMax: number
    if (typeof burstRaw === 'number' && Number.isFinite(burstRaw) && burstRaw >= refill) {
        poolMax = Math.min(Math.floor(burstRaw), MAX_BURST_LOGS)
    } else {
        poolMax = Math.min(refill * 3, MAX_BURST_LOGS)
    }
    return { refillPerSecond: refill, poolMax }
}

function parseAlwaysKeep(config: Record<string, unknown>): CompiledSamplingRule['alwaysKeep'] {
    const ak = config.always_keep as Record<string, unknown> | undefined
    if (!ak || typeof ak !== 'object') {
        return null
    }
    const statusGte = typeof ak.status_gte === 'number' ? ak.status_gte : null
    const latencyMsGt = typeof ak.latency_ms_gt === 'number' ? ak.latency_ms_gt : null
    const preds = Array.isArray(ak.attribute_predicates) ? (ak.attribute_predicates as any[]) : []
    const attributePredicates = preds
        .filter((p) => p && typeof p.key === 'string' && typeof p.op === 'string')
        .map((p) => ({
            key: p.key as string,
            op: p.op as string,
            value: typeof p.value === 'string' ? p.value : undefined,
        }))
    if (statusGte == null && latencyMsGt == null && attributePredicates.length === 0) {
        return null
    }
    return { statusGte, latencyMsGt, attributePredicates }
}

export function compileRuleSet(rows: SamplingRuleRow[]): CompiledRuleSet {
    const rules: CompiledSamplingRule[] = []
    let hasRateLimitRules = false
    for (const row of rows) {
        let pathRegex: RegExp | null = null
        if (row.scope_path_pattern) {
            try {
                pathRegex = new RegExp(row.scope_path_pattern)
            } catch {
                pathRegex = /^$/
            }
        }
        let pathDropPatterns: RegExp[] | null = null
        let pathDropMatchAttributeKey: string | null = null
        if (row.rule_type === 'path_drop') {
            const patterns = (row.config.patterns as unknown[]) || []
            pathDropPatterns = []
            for (const p of patterns) {
                if (typeof p !== 'string') {
                    continue
                }
                try {
                    pathDropPatterns.push(new RegExp(p))
                } catch {
                    /* skip invalid */
                }
            }
            const mak = row.config.match_attribute_key
            if (typeof mak === 'string') {
                const t = mak.trim()
                pathDropMatchAttributeKey = t === '' ? null : t
            }
        }
        const rt = row.rule_type as CompiledSamplingRule['ruleType']
        const ruleType: CompiledSamplingRule['ruleType'] =
            rt === 'path_drop' || rt === 'rate_limit' || rt === 'severity_sampling' ? rt : 'path_drop'
        let rateLimit: CompiledSamplingRule['rateLimit'] = null
        if (ruleType === 'rate_limit') {
            rateLimit = parseRateLimitFromConfig(row.config ?? {})
            if (rateLimit) {
                hasRateLimitRules = true
            }
        }
        rules.push({
            id: row.id,
            ruleType,
            scopeService: row.scope_service,
            pathRegex,
            pathDropPatterns,
            pathDropMatchAttributeKey,
            severityActions: parseSeverityActions(row.config),
            alwaysKeep: parseAlwaysKeep(row.config),
            rateLimit,
        })
    }
    return { rules, hasRateLimitRules }
}
