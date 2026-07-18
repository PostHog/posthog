import { createTrackedRE2 } from '~/common/utils/tracked-re2'

import type { CompiledRuleSet, CompiledSamplingRule, SeverityAction } from './evaluate'
import { type FilterGroupNode, MAX_FILTER_GROUP_DEPTH } from './filter-group-match'
import { type PropertyFilterLeaf, compileLeafRegex } from './property-filter-match'

/**
 * Bound on the total node count (groups + leaves) of a filter_group tree. Depth
 * alone does not bound per-record work: a single AND with thousands of sibling
 * leaves passes MAX_FILTER_GROUP_DEPTH but costs O(leaves) per log line. Kept
 * in sync with `MAX_FILTER_GROUP_NODES` in `products/logs/backend/sampling_api.py`.
 */
export const MAX_FILTER_GROUP_NODES = 256

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
const MAX_BURST_LOGS = 10_000_000
const MAX_KB_PER_SECOND = 1_000_000
const MAX_BURST_KB = 10_000_000
// Decimal (SI) KB: the drop-rule form (UNIT_TO_KB_PER_S), the sparkline preview's
// threshold line (KB/s × 1000), and the API validator ("1000000 = 1 GB/s") all use
// 1 KB = 1000 bytes. The bucket must charge in the same unit, otherwise every cap
// silently enforces ~2.4% above its label.
const BYTES_PER_KB = 1000

function parseRateLimitFromConfig(
    config: Record<string, unknown>
): { refillPerSecond: number; poolMax: number; costUnit: 'records' | 'bytes' } | null {
    // KB-mode takes precedence when both fields are set. The API validator rejects that
    // case at write time, but the ingestion path stays robust to legacy or hand-crafted rows.
    const kbps = config.kb_per_second
    if (typeof kbps === 'number' && Number.isFinite(kbps) && kbps >= 1 && kbps <= MAX_KB_PER_SECOND) {
        const refillKb = Math.floor(kbps)
        const burstRaw = config.burst_kb
        const burstKb =
            typeof burstRaw === 'number' && Number.isFinite(burstRaw) && burstRaw >= refillKb
                ? Math.min(Math.floor(burstRaw), MAX_BURST_KB)
                : Math.min(refillKb * 3, MAX_BURST_KB)
        return {
            refillPerSecond: refillKb * BYTES_PER_KB,
            poolMax: burstKb * BYTES_PER_KB,
            costUnit: 'bytes',
        }
    }
    const lps = config.logs_per_second
    if (typeof lps !== 'number' || !Number.isFinite(lps) || lps < 1 || lps > MAX_LOGS_PER_SECOND) {
        return null
    }
    const refill = Math.floor(lps)
    const burstRaw = config.burst_logs
    const poolMax =
        typeof burstRaw === 'number' && Number.isFinite(burstRaw) && burstRaw >= refill
            ? Math.min(Math.floor(burstRaw), MAX_BURST_LOGS)
            : Math.min(refill * 3, MAX_BURST_LOGS)
    return { refillPerSecond: refill, poolMax, costUnit: 'records' }
}

/**
 * The drop-rules UI writes the inner group wrapped in another AND envelope:
 *   { type: AND, values: [ { type: AND|OR, values: [<leaves>] } ] }
 * Earlier shapes may have stored the bare inner group. Accept either; reject
 * anything that doesn't look like a group.
 */
function parseFilterGroup(raw: unknown): FilterGroupNode | null {
    if (!raw || typeof raw !== 'object') {
        return null
    }
    const candidate = raw as { type?: unknown; values?: unknown }
    if (!Array.isArray(candidate.values) || (candidate.type !== 'AND' && candidate.type !== 'OR')) {
        return null
    }
    let parsed: FilterGroupNode = candidate as FilterGroupNode
    // If the outer envelope contains a single inner group, unwrap it.
    if (candidate.values.length === 1) {
        const inner = candidate.values[0] as { type?: unknown; values?: unknown } | null
        if (
            inner &&
            typeof inner === 'object' &&
            Array.isArray(inner.values) &&
            (inner.type === 'AND' || inner.type === 'OR')
        ) {
            parsed = inner as FilterGroupNode
        }
    }
    // Reject pathologically deep trees at compile time so the worker hot path
    // never recurses past MAX_FILTER_GROUP_DEPTH. Same bound is enforced in
    // sampling_api.py's Pydantic validator at write time; this is defense in
    // depth for rows that predate the validator.
    if (filterGroupDepth(parsed, 0) > MAX_FILTER_GROUP_DEPTH) {
        return null
    }
    // Also bound total breadth — a flat AND with thousands of sibling leaves
    // passes the depth check but costs O(leaves) per record. Matches the
    // server-side check in sampling_api.py and protects rows that predate it.
    if (filterGroupNodeCount(parsed) > MAX_FILTER_GROUP_NODES) {
        return null
    }
    // Walk the tree once and stamp pre-compiled regex onto each regex leaf so
    // the per-record hot path doesn't allocate a fresh `RegExp` per match.
    // Legacy `pathDropPatterns` already follow this pattern; this brings the
    // filter-group path in line.
    compileRegexLeavesInPlace(parsed)
    return parsed
}

function filterGroupNodeCount(node: FilterGroupNode | PropertyFilterLeaf): number {
    const maybe = node as { type?: unknown; values?: unknown }
    if (!Array.isArray(maybe.values) || (maybe.type !== 'AND' && maybe.type !== 'OR')) {
        return 1
    }
    let total = 1
    for (const child of maybe.values as Array<FilterGroupNode | PropertyFilterLeaf>) {
        total += filterGroupNodeCount(child)
        if (total > MAX_FILTER_GROUP_NODES) {
            return total
        }
    }
    return total
}

function filterGroupDepth(node: FilterGroupNode | PropertyFilterLeaf, depth: number): number {
    const maybe = node as { type?: unknown; values?: unknown }
    if (!Array.isArray(maybe.values) || (maybe.type !== 'AND' && maybe.type !== 'OR')) {
        return depth
    }
    let maxChild = depth
    for (const child of maybe.values as Array<FilterGroupNode | PropertyFilterLeaf>) {
        const d = filterGroupDepth(child, depth + 1)
        if (d > maxChild) {
            maxChild = d
        }
    }
    return maxChild
}

function compileRegexLeavesInPlace(node: FilterGroupNode | PropertyFilterLeaf): void {
    const maybe = node as { type?: unknown; values?: unknown }
    if (Array.isArray(maybe.values) && (maybe.type === 'AND' || maybe.type === 'OR')) {
        for (const child of maybe.values as Array<FilterGroupNode | PropertyFilterLeaf>) {
            compileRegexLeavesInPlace(child)
        }
        return
    }
    const leaf = node as PropertyFilterLeaf
    if (leaf.operator === 'regex' || leaf.operator === 'not_regex') {
        leaf._compiledRegex = leaf.value == null ? null : compileLeafRegex(leaf.value)
    }
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
        // RE2 has linear-time matching; native RegExp here would expose the ingestion
        // worker to catastrophic-backtracking ReDoS from any admin-authored pattern.
        // Same engine choice as the new filter-group regex leaves and the rest of
        // `nodejs/src/cdp/` regex sites.
        let pathRegex: CompiledSamplingRule['pathRegex'] = null
        if (row.scope_path_pattern) {
            try {
                pathRegex = createTrackedRE2(row.scope_path_pattern, undefined, 'logs-sampling:scope-path')
            } catch {
                // Treat invalid / RE2-rejected patterns as match-nothing so the rule
                // never accidentally over-scopes. Mirrors prior `/^$/` sentinel.
                pathRegex = createTrackedRE2('^$', undefined, 'logs-sampling:scope-path-fallback')
            }
        }
        let pathDropPatterns: CompiledSamplingRule['pathDropPatterns'] = null
        let pathDropMatchAttributeKey: string | null = null
        let filterGroup: FilterGroupNode | null = null
        if (row.rule_type === 'path_drop') {
            // Array.isArray, not truthiness: a corrupt string value would otherwise be
            // iterated per character into single-char regexes that match nearly everything.
            const patterns = Array.isArray(row.config.patterns) ? (row.config.patterns as unknown[]) : []
            pathDropPatterns = []
            for (const p of patterns) {
                if (typeof p !== 'string') {
                    continue
                }
                try {
                    pathDropPatterns.push(createTrackedRE2(p, undefined, 'logs-sampling:path-drop-pattern'))
                } catch {
                    /* skip invalid (incl. RE2-rejected lookahead/backreference patterns) */
                }
            }
            const mak = row.config.match_attribute_key
            if (typeof mak === 'string') {
                const t = mak.trim()
                pathDropMatchAttributeKey = t === '' ? null : t
            }
            filterGroup = parseFilterGroup(row.config.filter_group)
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
            // rate_limit rules also accept config.filter_group as a universal scope (the
            // drop-rule UI now writes service-scoping there instead of scope_service).
            // The path_drop branch above already parsed any filter_group on path_drop rows;
            // do the same parse for rate_limit so the evaluator can honor it.
            filterGroup = parseFilterGroup(row.config?.filter_group)
        }
        rules.push({
            id: row.id,
            ruleType,
            scopeService: row.scope_service,
            pathRegex,
            pathDropPatterns,
            pathDropMatchAttributeKey,
            filterGroup,
            severityActions: parseSeverityActions(row.config),
            alwaysKeep: parseAlwaysKeep(row.config),
            rateLimit,
        })
    }
    return { rules, hasRateLimitRules }
}
