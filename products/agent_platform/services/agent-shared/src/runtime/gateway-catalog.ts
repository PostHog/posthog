/**
 * Gateway model catalog — the agent platform's source of truth for which
 * models are runnable, their pricing, and their context window.
 *
 * Reads the SAME gateway the runner dispatches against (`GET {baseUrl}/models`),
 * so author-time validation and runtime resolution agree with what will
 * actually run. The curated tier groupings (`MODEL_POLICY_LEVELS` in spec.ts)
 * are reconciled against this: the catalog says what's *possible*, the groups
 * say what's *meaningful*. A model string is only real if it appears here.
 */

import { MODEL_POLICY_LEVELS, type ModelEntry, type ModelPolicy, type ModelLevel } from '../spec/spec'
import type { HttpFetcher } from './http-client'
import { createLogger } from './logger'

/** Per-token USD costs. `cache_*` are per-model-optional (OpenAI has no
 *  cache_write; bare models have neither). */
export interface CatalogModelPricing {
    prompt: number
    completion: number
    cache_read?: number
    cache_write?: number
}

/** One served model, normalized from the gateway's `/v1/models` row. */
export interface CatalogModel {
    /** Stable provider-prefixed id, e.g. `anthropic/claude-haiku-4.5`. Prefer this everywhere. */
    canonical: string
    /** Advertised provider SKU, e.g. `claude-haiku-4-5-20251001`. */
    id: string
    /** Other accepted spellings (e.g. the undated `claude-haiku-4-5`). */
    aliases: string[]
    /** Primary provider, e.g. `anthropic`. */
    owned_by: string
    /** Max context window in tokens (0 when the gateway didn't report it). */
    context_window: number
    pricing: CatalogModelPricing
}

/** Async accessor over the cached catalog. */
export interface GatewayCatalog {
    /** All served models. Cached; refreshes past the TTL; serves last-good
     *  through a transient gateway failure (empty only if never fetched). */
    list(): Promise<CatalogModel[]>
}

// ── Wire shape (GET /v1/models) ──────────────────────────────────────────
// Pricing values arrive as decimal strings to preserve precision; parse at
// the boundary.
interface WirePricing {
    prompt?: string
    completion?: string
    cache_read?: string
    cache_write?: string
}
interface WireModel {
    id?: string
    canonical?: string
    owned_by?: string
    context_window?: number
    aliases?: string[] | null
    pricing?: WirePricing
}
interface WireResponse {
    data?: WireModel[]
}

function parseDecimal(s: string | undefined): number | undefined {
    if (s === undefined) {
        return undefined
    }
    const n = Number(s)
    return Number.isFinite(n) ? n : undefined
}

function parseModel(w: WireModel): CatalogModel | null {
    // A row without an id, canonical, or usable input/output price isn't
    // routable+billable, so it isn't part of the vocabulary.
    if (!w.id || !w.canonical || !w.pricing) {
        return null
    }
    const prompt = parseDecimal(w.pricing.prompt)
    const completion = parseDecimal(w.pricing.completion)
    if (prompt === undefined || completion === undefined) {
        return null
    }
    return {
        canonical: w.canonical,
        id: w.id,
        aliases: (w.aliases ?? []).filter((a): a is string => typeof a === 'string'),
        owned_by: w.owned_by ?? w.canonical.split('/')[0] ?? '',
        context_window: typeof w.context_window === 'number' ? w.context_window : 0,
        pricing: {
            prompt,
            completion,
            cache_read: parseDecimal(w.pricing.cache_read),
            cache_write: parseDecimal(w.pricing.cache_write),
        },
    }
}

// ── Pure reconciliation helpers (catalog snapshot in, decision out) ───────
// Kept pure so they're testable without a live gateway and reusable from the
// runner (runtime resolution) and janitor (author-time validation).

/** Every string the gateway would accept for a model: canonical, its bare
 *  suffix, the SKU id, each alias, and the provider-prefixed id/aliases. This
 *  mirrors the gateway resolver's acceptance set so client-side checks match
 *  what dispatch will accept. */
export function acceptedModelIds(models: CatalogModel[]): Set<string> {
    const out = new Set<string>()
    for (const m of models) {
        out.add(m.canonical)
        const slash = m.canonical.indexOf('/')
        if (slash > 0) {
            out.add(m.canonical.slice(slash + 1))
        }
        out.add(m.id)
        if (m.owned_by) {
            out.add(`${m.owned_by}/${m.id}`)
        }
        for (const alias of m.aliases) {
            out.add(alias)
            if (m.owned_by) {
                out.add(`${m.owned_by}/${alias}`)
            }
        }
    }
    return out
}

/** True if the gateway serves `modelId` in any accepted form. */
export function isModelServable(models: CatalogModel[], modelId: string): boolean {
    return acceptedModelIds(models).has(modelId)
}

export interface ModelPolicyIssue {
    model: string
    pointer: string
    reason: string
}

/**
 * Author-time validation of a `models` against the catalog. `manual`:
 * each listed model must be servable (author's to fix). `auto`: only flagged
 * when the level resolves to nothing servable — a single dead tier member is
 * platform drift, caught by `validateModelLevels` in CI, not the author's
 * problem.
 *
 * Catalog availability gates the SERVABILITY check (empty → fail-open, see
 * HttpGatewayCatalog) but NOT the FORMAT check: a bare model id like
 * `haiku-4-5` will 400 at the gateway regardless of catalog state, and we'd
 * rather catch it at freeze than ship a session that fails on the first call.
 */
// Mirror of `ModelIdSchema` in agent-shared/src/spec/spec.ts (the single
// source of truth for the id format) — keep the two in sync.
const MODEL_ID_PATTERN = /^[a-z0-9_-]+\/[a-zA-Z0-9._:-]+$/

export function validateModelPolicy(policy: ModelPolicy, models: CatalogModel[]): ModelPolicyIssue[] {
    const issues: ModelPolicyIssue[] = []
    if (policy.mode === 'manual') {
        // Format check runs unconditionally — see the function docstring.
        policy.models.forEach((entry, i) => {
            if (!MODEL_ID_PATTERN.test(entry.model)) {
                issues.push({
                    model: entry.model,
                    pointer: `spec.models.models[${i}].model`,
                    reason: 'must be "<provider>/<model-id>"',
                })
            }
        })
        if (models.length === 0) {
            return issues
        }
        const accepted = acceptedModelIds(models)
        policy.models.forEach((entry, i) => {
            // Skip the servability check if the id is already malformed —
            // the format error above is the more actionable signal.
            if (MODEL_ID_PATTERN.test(entry.model) && !accepted.has(entry.model)) {
                issues.push({
                    model: entry.model,
                    pointer: `spec.models.models[${i}].model`,
                    reason: 'not served by the gateway',
                })
            }
        })
        return issues
    }
    if (models.length === 0) {
        return issues
    }
    const accepted = acceptedModelIds(models)
    const members = MODEL_POLICY_LEVELS[policy.level] ?? []
    if (members.some((m) => accepted.has(m))) {
        return issues
    }
    issues.push({
        model: members.join(', ') || policy.level,
        pointer: 'spec.models.level',
        reason: `level "${policy.level}" resolves to no model the gateway currently serves`,
    })
    return issues
}

/**
 * CI/test guard: every model in the curated `MODEL_POLICY_LEVELS` must be
 * servable. Catches drift between the hand-maintained tiers and the live
 * catalog (e.g. a tier pointing at a delisted SKU) before it reaches an
 * `auto` agent at runtime. Returns one issue per dead tier member.
 */
export function validateModelLevels(models: CatalogModel[]): ModelPolicyIssue[] {
    const accepted = acceptedModelIds(models)
    const issues: ModelPolicyIssue[] = []
    for (const level of Object.keys(MODEL_POLICY_LEVELS) as ModelLevel[]) {
        for (const model of MODEL_POLICY_LEVELS[level]) {
            if (!accepted.has(model)) {
                issues.push({
                    model,
                    pointer: `MODEL_POLICY_LEVELS.${level}`,
                    reason: 'tier member not served by the gateway',
                })
            }
        }
    }
    return issues
}

/**
 * Runtime servability filter: keep only entries the catalog serves. If that
 * would drop everything (stale/empty catalog, or a manual list the catalog
 * doesn't know yet), return the original list unchanged — never strand a live
 * session on a catalog hiccup. The author-time gate is where bad models get
 * rejected; this is belt-and-suspenders.
 */
export function filterServableEntries(entries: ModelEntry[], models: CatalogModel[]): ModelEntry[] {
    if (models.length === 0) {
        return entries
    }
    const accepted = acceptedModelIds(models)
    const kept = entries.filter((e) => accepted.has(e.model))
    return kept.length > 0 ? kept : entries
}

// ── HTTP catalog client ──────────────────────────────────────────────────

export interface HttpGatewayCatalogOpts {
    /** Gateway base URL incl. version, e.g. `http://localhost:8080/v1`. */
    baseUrl: string
    /** `phs_` bearer with `llm_gateway:read`. Sent when set; the /models
     *  read is otherwise unauthenticated. */
    bearer?: string
    /**
     * Outbound HTTP. Wire a `DirectHttpClient` — the gateway is
     * cluster-internal and smokescreen would deny it as RFC1918. Never pass
     * the proxy-bound `HttpClient`.
     */
    http: HttpFetcher
    /** Cache TTL in ms. Default 60_000. */
    ttlMs?: number
    /** Per-fetch timeout in ms. Default 5_000. */
    timeoutMs?: number
}

export class HttpGatewayCatalog implements GatewayCatalog {
    private readonly log = createLogger('gateway-catalog')
    private readonly baseUrl: string
    private readonly bearer: string | undefined
    private readonly http: HttpFetcher
    private readonly ttlMs: number
    private readonly timeoutMs: number
    private cache: { at: number; models: CatalogModel[] } | null = null
    private inflight: Promise<CatalogModel[]> | null = null

    constructor(opts: HttpGatewayCatalogOpts) {
        this.baseUrl = opts.baseUrl.replace(/\/$/, '')
        this.bearer = opts.bearer
        this.http = opts.http
        this.ttlMs = opts.ttlMs ?? 60_000
        this.timeoutMs = opts.timeoutMs ?? 5_000
    }

    async list(): Promise<CatalogModel[]> {
        if (this.cache && Date.now() - this.cache.at < this.ttlMs) {
            return this.cache.models
        }
        if (this.inflight) {
            return this.inflight
        }
        this.inflight = this.fetchModels()
            .then((models) => {
                this.cache = { at: Date.now(), models }
                return models
            })
            .catch((err) => {
                // Serve last-good through a transient gateway blip; never throw
                // — a catalog read must not be able to fail a promote or a
                // session. Empty only when we've never had a good fetch.
                this.log.warn({ err: err instanceof Error ? err.message : String(err) }, 'gateway_catalog_fetch_failed')
                return this.cache?.models ?? []
            })
            .finally(() => {
                this.inflight = null
            })
        return this.inflight
    }

    private async fetchModels(): Promise<CatalogModel[]> {
        const headers: Record<string, string> = { Accept: 'application/json' }
        if (this.bearer) {
            headers.Authorization = `Bearer ${this.bearer}`
        }
        const res = await this.http.fetch(`${this.baseUrl}/models`, {
            method: 'GET',
            headers,
            signal: AbortSignal.timeout(this.timeoutMs),
        })
        if (!res.ok) {
            throw new Error(`gateway /models HTTP ${res.status}`)
        }
        const body = (await res.json()) as WireResponse
        const models = (body.data ?? []).map(parseModel).filter((m): m is CatalogModel => m !== null)
        this.log.debug({ count: models.length }, 'gateway_catalog_loaded')
        return models
    }
}
