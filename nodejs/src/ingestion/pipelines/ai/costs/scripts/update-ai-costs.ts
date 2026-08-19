import fs from 'fs'
import bigDecimal from 'js-big-decimal'
import path from 'path'

import { normalizeProviderKey } from '~/ingestion/pipelines/ai/costs/provider-matching'
import type { ModelCost } from '~/ingestion/pipelines/ai/costs/providers/types'

interface ModelRow {
    model: string
    cost: Record<string, ModelCost>
}

const PATH_TO_PROVIDERS = path.join(__dirname, '../providers')
const OPENROUTER_COSTS_FILENAME = 'llm-costs.json'

const parsePricingNumber = (value: unknown): number | undefined => {
    if (value === null || value === undefined) {
        return undefined
    }

    const valueAsString = typeof value === 'number' ? value.toString() : value
    if (typeof valueAsString !== 'string') {
        return undefined
    }

    try {
        const decimalValue = new bigDecimal(valueAsString).getValue()
        const parsed = parseFloat(decimalValue)
        if (Number.isNaN(parsed)) {
            return undefined
        }

        if (parsed < 0) {
            return 0
        }

        // Round to 10 significant digits to eliminate IEEE 754 floating-point
        // representation artifacts (e.g. 1.0000000000000001e-7 → 1e-7)
        return parseFloat(parsed.toPrecision(10))
    } catch (error) {
        console.warn('Failed to parse pricing value:', value, error)
        return undefined
    }
}

/** Carried at the served price: the live feed corroborates this for `web_search`,
 * where promotional routes serve the same fee as their undiscounted siblings. It
 * corroborates neither `request` (no model in the feed carries a non-zero fee)
 * nor a markup route (a negative rate has no sibling); both stay flat by policy. */
export const FLAT_FEE_FIELDS: ReadonlySet<keyof ModelCost> = new Set(['request', 'web_search'])

/** A field added here and not to `FLAT_FEE_FIELDS` is de-discounted by default.
 * `cache_write_1h_token` has no pair on purpose: OpenRouter serves no 1h write
 * rate. Book-priced events fall back to 2x `prompt_token` (input-costs.ts); only
 * the custom-pricing path reads it from event properties. */
export const OPTIONAL_PRICING_FIELDS: ReadonlyArray<[keyof ModelCost, string]> = [
    ['cache_read_token', 'input_cache_read'],
    ['cache_write_token', 'input_cache_write'],
    ['request', 'request'],
    ['web_search', 'web_search'],
    ['image', 'image'],
    ['image_output', 'image_output'],
    ['audio', 'audio'],
    ['audio_output', 'audio_output'],
    ['input_audio_cache', 'input_audio_cache'],
    ['internal_reasoning', 'internal_reasoning'],
]

/** A provider key means what that provider charges a direct caller, so whatever
 * OpenRouter applied is divided back out. A negative `discount_to_user` is a
 * markup and the same division recovers list; only a rate at or above 1 is
 * invalid, which OpenRouter itself falls back to no rate. */
export const parseDiscountRate = (pricing: Record<string, unknown>, context?: string, warn = true): number => {
    const raw = pricing.discount
    if (raw === undefined || raw === null) {
        return 0
    }

    // Classify before parsing: Number() never throws, so an unusable rate cannot
    // draw a second parse-failure log from parsePricingNumber for the same field.
    const asNumber =
        typeof raw === 'number' ? raw : typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : Number.NaN
    if (!Number.isFinite(asNumber) || asNumber >= 1) {
        if (warn) {
            console.warn(`Ignoring unusable discount ${String(raw)} for ${context ?? 'unknown model'}`)
        }
        return 0
    }

    // parsePricingNumber clamps negatives to 0, which would erase a markup.
    return asNumber < 0 ? asNumber : (parsePricingNumber(raw) ?? 0)
}

/** Keeps a cost at the served price by hiding the rate from the shared builder. */
export const withoutDiscount = (pricing: Record<string, unknown> | undefined): Record<string, unknown> | undefined => {
    if (!pricing) {
        return undefined
    }
    const { discount: _rate, ...rest } = pricing
    return rest
}

/** `default` must stay at the served price whatever the list payload carries. */
export const buildDefaultCost = (
    modelPricing: Record<string, unknown> | undefined,
    context?: string
): ModelCost | null => buildModelCost(withoutDiscount(modelPricing), context)

export const buildModelCost = (pricing: Record<string, unknown> | undefined, context?: string): ModelCost | null => {
    if (!pricing) {
        return null
    }

    const promptToken = parsePricingNumber(pricing.prompt)
    const completionToken = parsePricingNumber(pricing.completion)

    if (promptToken === undefined || completionToken === undefined) {
        return null
    }

    const discount = parseDiscountRate(pricing, context)
    const toListPrice = (value: number): number =>
        discount === 0 ? value : parseFloat((value / (1 - discount)).toPrecision(10))

    const cost: ModelCost = {
        prompt_token: toListPrice(promptToken),
        completion_token: toListPrice(completionToken),
    }

    for (const [targetField, sourceField] of OPTIONAL_PRICING_FIELDS) {
        const parsedValue = parsePricingNumber(pricing[sourceField])
        if (parsedValue !== undefined && parsedValue !== 0) {
            cost[targetField] = FLAT_FEE_FIELDS.has(targetField) ? parsedValue : toListPrice(parsedValue)
        }
    }

    return cost
}

export interface EndpointCandidate {
    key: string
    cost: ModelCost
    discount: number
}

/*
 * `default` keeps the promotion. `PROVIDER_ALIASES` maps `$ai_provider:
 * 'openrouter'` onto it, and for those callers the promo price is what they were
 * billed, so raising it to list over-reports them by 1/(1 - rate). Splitting the
 * two readers needs an `openrouter` key in `CanonicalProvider` first.
 */

export type DiscountConfirmation = 'confirmed' | 'unconfirmed' | 'not-checkable'

/** Corroborates one route's de-discount against an undiscounted sibling. Per
 * route, or a verdict rolled up across a model's routes gets displayed against
 * one it never checked. Evidence only: two hosts legitimately price the same
 * model differently, so a mismatch fires on half of all checkable routes. */
export const confirmDiscountAgainstSiblings = (
    candidate: EndpointCandidate,
    candidates: EndpointCandidate[]
): DiscountConfirmation => {
    const undiscounted = candidates.filter((other) => other.discount === 0)
    if (candidate.discount === 0 || undiscounted.length === 0) {
        return 'not-checkable'
    }

    // Both sides already went through the same rounding, so exact equality holds.
    return undiscounted.some((other) => other.cost.prompt_token === candidate.cost.prompt_token)
        ? 'confirmed'
        : 'unconfirmed'
}

export interface DiscountReportEntry {
    model: string
    endpoints: Array<{ key: string; discount: number; confirmation: DiscountConfirmation }>
}

/** Share of the catalogue that may go unchecked before the run says so loudly. */
export const UNCHECKED_WARN_FRACTION = 0.1

/** Table rows rendered before the remainder collapses into a count line. */
export const DISCOUNT_REPORT_ROW_LIMIT = 200

/** Confines a third-party string to inert text in one table cell. An allowlist,
 * because a denylist has to anticipate every markdown construct that renders. */
export const sanitizeReportCell = (value: string): string =>
    value
        .replace(/[\r\n]+/g, ' ')
        .replace(/[^A-Za-z0-9._:/ -]+/g, '')
        .trim()
        .slice(0, 120)

/** Renders promotions as line items in the generated PR. `uncheckedModels` is
 * reported too, so a bare "no discounts" cannot read as a verified negative. */
export const renderDiscountReport = (entries: DiscountReportEntry[], uncheckedModels = 0): string => {
    const unchecked =
        uncheckedModels > 0
            ? `\n${uncheckedModels} model(s) could not be checked (endpoint pricing unavailable); their prices may still carry a promotion.\n`
            : ''

    if (entries.length === 0) {
        return `## Discounts\n\nNo discounted endpoints found in this run.\n${unchecked}`
    }

    const rows = [...entries].sort((a, b) => a.model.localeCompare(b.model))
    const verdicts = rows.map((row) => row.endpoints.map((e) => e.confirmation))
    const confirmed = verdicts.filter((v) => v.includes('confirmed')).length
    const checkable = verdicts.filter((v) => v.some((c) => c !== 'not-checkable')).length
    const endpointCount = rows.reduce((total, row) => total + row.endpoints.length, 0)

    const flatFeeList = [...FLAT_FEE_FIELDS]
        .sort()
        .map((field) => `\`${field}\``)
        .join(', ')

    const lines = [
        '## Discounts',
        '',
        `OpenRouter is running a promotion on **${endpointCount} endpoint(s)** across **${rows.length} model(s)**.`,
        'Per-provider keys below are stored at list rate, with the promotion divided back',
        'out, so a provider key keeps meaning what that provider charges a direct caller.',
        `Per-call fees (${flatFeeList}) carry across untouched: promotional routes in`,
        'the feed serve `web_search` at the same fee as their undiscounted siblings,',
        'and every other per-call fee follows the same policy.',
        'The `default` key is left as OpenRouter serves it.',
        '',
        `Independently confirmed against an undiscounted sibling route: ${confirmed}/${checkable} checkable model(s).`,
        unchecked,
        '| Model | Endpoint | Rate | Confirmed |',
        '| --- | --- | --- | --- |',
    ]

    // Bounded on emitted rows, not models: the widest model carries 32 endpoints,
    // so a model cap would not bound the body GitHub has to accept.
    let emitted = 0
    let omittedModels = 0
    for (const row of rows) {
        if (emitted + row.endpoints.length > DISCOUNT_REPORT_ROW_LIMIT) {
            omittedModels += 1
            continue
        }
        for (const [index, endpoint] of row.endpoints.entries()) {
            const model = index === 0 ? sanitizeReportCell(row.model) : ''
            const confirmation = endpoint.confirmation
            lines.push(
                `| ${model} | \`${sanitizeReportCell(endpoint.key)}\` | ${Math.round(endpoint.discount * 100)}% | ${confirmation} |`
            )
        }
        emitted += row.endpoints.length
    }
    if (omittedModels > 0) {
        lines.push('', `...and ${omittedModels} more discounted model(s) not listed.`)
    }

    lines.push('')
    return lines.join('\n')
}

/** Shared with provider-matching: this writes the keys that module reads. */
const endpointProviderKey = (endpoint: { tag?: string; provider_name?: string; name?: string }): string =>
    normalizeProviderKey(endpoint.tag || endpoint.provider_name || endpoint.name || 'unknown')

export interface BuiltModelRow {
    cost: Record<string, ModelCost>
    discount?: DiscountReportEntry
    /** False when no endpoint yielded usable pricing, so nothing was checked for promotions. */
    checked: boolean
}

/** Turns one model's payloads into the row that gets written, plus what the
 * discount report says about it. */
export const buildModelRow = (
    modelId: string,
    modelPricing: Record<string, unknown> | undefined,
    endpoints: unknown[]
): BuiltModelRow | null => {
    const defaultCost = buildDefaultCost(modelPricing, modelId)
    if (!defaultCost) {
        return null
    }
    const cost: Record<string, ModelCost> = { default: defaultCost }
    const candidates: EndpointCandidate[] = []

    for (const raw of endpoints) {
        const endpoint = (raw ?? {}) as { tag?: string; provider_name?: string; pricing?: Record<string, unknown> }
        const context = `${modelId} (${endpoint.tag ?? '?'})`
        const endpointCost = buildModelCost(endpoint.pricing, context)
        if (!endpointCost) {
            continue
        }

        const providerKey = endpointProviderKey(endpoint)
        // Normalized too: every key here is interpolated into canonical-providers.ts
        // as a string literal, so it must be [a-z0-9-] by construction.
        const safeProviderKey =
            providerKey && providerKey !== 'default'
                ? providerKey
                : `provider-${normalizeProviderKey(endpoint.provider_name ?? 'unknown') || 'unknown'}`

        cost[safeProviderKey] = endpointCost
        candidates.push({
            key: safeProviderKey,
            cost: endpointCost,
            discount: parseDiscountRate(endpoint.pricing ?? {}, context, false),
        })
    }

    // Keyed on parsed candidates rather than the raw endpoint count: a payload
    // whose entries all fail to parse yielded nothing to check either.
    if (candidates.length === 0) {
        return { cost, checked: false }
    }

    const discounted = candidates.filter((candidate) => candidate.discount > 0)
    return {
        cost,
        checked: true,
        discount:
            discounted.length > 0
                ? {
                      model: modelId,
                      endpoints: discounted.map((candidate) => ({
                          key: candidate.key,
                          discount: candidate.discount,
                          confirmation: confirmDiscountAgainstSiblings(candidate, candidates),
                      })),
                  }
                : undefined,
    }
}

export interface RunTotals {
    models: ModelRow[]
    discounts: DiscountReportEntry[]
    uncheckedModels: number
}

/** Folds one built row into the run totals; split out so a test can cover the
 * wire between what `buildModelRow` reports and what the summary claims. */
export const accumulateModelRow = (built: BuiltModelRow, modelId: string, totals: RunTotals): RunTotals => ({
    models: [...totals.models, { model: modelId, cost: built.cost }],
    discounts: built.discount ? [...totals.discounts, built.discount] : totals.discounts,
    uncheckedModels: totals.uncheckedModels + (built.checked ? 0 : 1),
})

/** Skips a model whose list pricing will not parse, keeping what came before. */
export const foldModelIntoTotals = (
    modelId: string,
    modelPricing: Record<string, unknown> | undefined,
    endpoints: unknown[],
    totals: RunTotals
): RunTotals => {
    const built = buildModelRow(modelId, modelPricing, endpoints)
    if (!built) {
        console.warn('Skipping model without valid pricing:', modelId)
        return totals
    }
    return accumulateModelRow(built, modelId, totals)
}

/** Orders by model id: inheriting response order rewrites the whole file each run. */
export const finalizeTotals = (totals: RunTotals): RunTotals => ({
    ...totals,
    models: [...totals.models].sort((a, b) => a.model.localeCompare(b.model)),
})

/** Name of the env var carrying the summary path, shared with the workflow that sets it. */
export const DISCOUNT_SUMMARY_ENV = 'DISCOUNT_SUMMARY_PATH'

/** The summary only decorates a PR body, so it goes last and cannot throw away a
 * completed run's fetching. */
export const writeOutputs = (sortedCosts: ModelRow[], discounts: DiscountReportEntry[], unchecked: number): void => {
    fs.writeFileSync(path.join(PATH_TO_PROVIDERS, OPENROUTER_COSTS_FILENAME), JSON.stringify(sortedCosts, null, 4))
    console.log(`Wrote OpenRouter costs to ${OPENROUTER_COSTS_FILENAME}`)

    generateCanonicalProviders(sortedCosts)

    const summaryPath = process.env[DISCOUNT_SUMMARY_ENV]
    console.log(`Found discounted endpoints on ${discounts.length} model(s)`)
    if (!summaryPath) {
        return
    }
    try {
        fs.writeFileSync(summaryPath, renderDiscountReport(discounts, unchecked))
        console.log(`Wrote discount summary to ${summaryPath}`)
    } catch (error) {
        console.warn('Failed to write discount summary:', error)
    }
}

/** Reads one model's endpoints payload. Split out so the loop is testable. */
export type EndpointFetcher = (modelId: string) => Promise<unknown[]>

interface ListedModel {
    id?: string
    pricing?: Record<string, unknown>
}

/** Takes the endpoint reader as an argument so this loop is reachable without a
 * network. */
export const collectModelRows = async (models: ListedModel[], readEndpoints: EndpointFetcher): Promise<RunTotals> => {
    let totals: RunTotals = { models: [], discounts: [], uncheckedModels: 0 }

    for (const [modelIndex, model] of models.entries()) {
        if (!model?.id) {
            console.warn('Skipping model without id:', model)
            continue
        }

        console.log(`Fetching endpoint pricing for ${modelIndex + 1}/${models.length} ${model.id}...`)
        totals = foldModelIntoTotals(model.id, model.pricing, await readEndpoints(model.id), totals)
    }

    if (totals.uncheckedModels > 0) {
        // Alias and meta-router models have no per-endpoint pricing, so a handful is
        // the steady state; the denominator separates that from a degraded API.
        const line = `${totals.uncheckedModels}/${models.length} model(s) had no usable endpoint pricing`
        if (totals.uncheckedModels > models.length * UNCHECKED_WARN_FRACTION) {
            console.warn(`${line}: endpoint pricing looks degraded, per-provider prices are missing`)
        } else {
            console.log(line)
        }
    }

    return finalizeTotals(totals)
}

/** Endpoint reader against the live API. Every failure degrades to no endpoints. */
export const readEndpointsFromOpenRouter: EndpointFetcher = async (modelId) => {
    const encoded = modelId
        .split('/')
        .map((segment: string) => encodeURIComponent(segment))
        .join('/')

    try {
        // eslint-disable-next-line no-restricted-globals
        const res = await fetch(`https://openrouter.ai/api/v1/models/${encoded}/endpoints`, {})
        if (!res.ok) {
            console.warn(`Failed to fetch endpoint pricing for ${modelId}: ${res.status} ${res.statusText}`)
            return []
        }
        const payload = await res.json()
        return payload?.data?.endpoints ?? []
    } catch (error) {
        console.warn('Error fetching endpoint pricing for model:', modelId, error)
        return []
    }
}

export const fetchOpenRouterCosts = async (): Promise<RunTotals> => {
    // eslint-disable-next-line no-restricted-globals
    const res = await fetch('https://openrouter.ai/api/v1/models', {})
    if (!res.ok) {
        throw new Error(`Failed to fetch OpenRouter models: ${res.status} ${res.statusText}`)
    }

    let data
    try {
        data = await res.json()
    } catch {
        throw new Error('Failed to parse OpenRouter API response as JSON')
    }

    console.log('OpenRouter models:', data.data.length)
    return collectModelRows(data.data, readEndpointsFromOpenRouter)
}

const sortProviderCosts = (models: ModelRow[]): ModelRow[] => {
    return models.map((model) => {
        const sortedCost: Record<string, ModelCost> = {}

        // Get all provider keys and sort them
        const providerKeys = Object.keys(model.cost)
        const otherProviders = providerKeys.filter((key) => key !== 'default').sort()

        // Always put 'default' first, then add the rest alphabetically
        if (model.cost.default) {
            sortedCost.default = model.cost.default
        }

        for (const provider of otherProviders) {
            sortedCost[provider] = model.cost[provider]
        }

        return {
            ...model,
            cost: sortedCost,
        }
    })
}

const generateCanonicalProviders = (models: ModelRow[]): void => {
    // Extract all unique provider keys from the cost data
    const providerSet = new Set<string>()

    for (const model of models) {
        for (const providerKey of Object.keys(model.cost)) {
            providerSet.add(providerKey)
        }
    }

    // Sort deterministically: default first, then alphabetically
    const allProviders = Array.from(providerSet)
    const otherProviders = allProviders.filter((p) => p !== 'default').sort()
    const providers = allProviders.includes('default') ? ['default', ...otherProviders] : otherProviders

    // Generate TypeScript file content
    const now = new Date()
    const timestamp = `${now.toISOString().split('.')[0].replace('T', ' ')} UTC`
    const typeUnion = providers.map((p) => `    | '${p}'`).join('\n')

    const fileContent = `// Auto-generated from OpenRouter API - Do not edit manually
// Generated at: ${timestamp}

export type CanonicalProvider =
${typeUnion}
`

    // Write the file
    const filePath = path.join(PATH_TO_PROVIDERS, 'canonical-providers.ts')
    fs.writeFileSync(filePath, fileContent)
    console.log(`Generated canonical-providers.ts with ${providers.length} provider types`)
}

const main = async () => {
    // Create main directory if it doesn't exist
    if (!fs.existsSync(PATH_TO_PROVIDERS)) {
        fs.mkdirSync(PATH_TO_PROVIDERS)
    }

    // Fetch costs from both providers
    console.log('Fetching costs from OpenRouter...')
    const { models: openRouterCosts, discounts, uncheckedModels } = await fetchOpenRouterCosts()
    console.log(`Fetched ${openRouterCosts.length} models from OpenRouter`)

    // Sort provider costs deterministically (default first, then alphabetically)
    const sortedCosts = sortProviderCosts(openRouterCosts)

    writeOutputs(sortedCosts, discounts, uncheckedModels)
}

// Only run when invoked directly (`pnpm update-ai-costs`). Importing this
// module from a test must not fetch the live API or rewrite the generated files.
if (require.main === module) {
    ;(async () => {
        await main()
    })().catch((e) => {
        console.error('Error updating AI costs:', e)
        process.exit(1)
    })
}
