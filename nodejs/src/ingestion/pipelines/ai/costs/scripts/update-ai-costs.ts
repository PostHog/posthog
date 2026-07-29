import fs from 'fs'
import bigDecimal from 'js-big-decimal'
import path from 'path'

interface ModelCost {
    prompt_token: number
    completion_token: number
    cache_read_token?: number
    cache_write_token?: number
    request?: number
    web_search?: number
    image?: number
    image_output?: number
    audio?: number
    audio_output?: number
    input_audio_cache?: number
    internal_reasoning?: number
}

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

/**
 * OpenRouter serves `pricing.*` net of any promotion and reports the rate here.
 * A provider key means "what this provider charges a direct caller", so the
 * promotion is divided back out. Returns 0 for absent, zero, or out-of-range.
 */
export const parseDiscountRate = (pricing: Record<string, unknown>, context?: string, warn = true): number => {
    const parsed = parsePricingNumber(pricing.discount)
    if (parsed === undefined) {
        return 0
    }

    // A rate at or above 1 would divide by zero or flip the sign. Negatives read
    // the raw value because parsePricingNumber clamps them to 0, which would
    // otherwise be indistinguishable from "no promotion".
    if (parsed >= 1 || Number(pricing.discount) < 0) {
        if (warn) {
            console.warn(`Ignoring out-of-range discount ${String(pricing.discount)} for ${context ?? 'unknown model'}`)
        }
        return 0
    }

    return parsed
}

/**
 * Strips the promotion rate so a cost built from this pricing keeps the price as
 * served. `default` mirrors the list payload, and sharing `buildModelCost` would
 * otherwise de-discount it the day OpenRouter adds the field to that payload.
 */
export const withoutDiscount = (pricing: Record<string, unknown> | undefined): Record<string, unknown> | undefined => {
    if (!pricing) {
        return undefined
    }
    const { discount: _rate, ...rest } = pricing
    return rest
}

/**
 * Builds the `default` cost. Routed through `withoutDiscount` so the shared
 * builder cannot de-discount it, whatever the list payload starts carrying.
 */
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

    // The rate applies uniformly to every price field, flat fees included: on a
    // 50%-off endpoint web_search reads 0.005 against 0.01 on the undiscounted
    // sibling, the same ratio as the token rates.
    const discount = parseDiscountRate(pricing, context)
    const toListPrice = (value: number): number =>
        discount === 0 ? value : parseFloat((value / (1 - discount)).toPrecision(10))

    const cost: ModelCost = {
        prompt_token: toListPrice(promptToken),
        completion_token: toListPrice(completionToken),
    }

    const optionalPricingFields: Array<[keyof ModelCost, string]> = [
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

    for (const [targetField, sourceField] of optionalPricingFields) {
        const parsedValue = parsePricingNumber(pricing[sourceField])
        if (parsedValue !== undefined && parsedValue !== 0) {
            cost[targetField] = toListPrice(parsedValue)
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
 * `default` holds the `/api/v1/models` list price, promotion included, and no
 * de-discount is applied to it: `PROVIDER_ALIASES` maps `$ai_provider:
 * 'openrouter'` onto `default`, where the promo price is what the caller was
 * billed. Raising it to list over-reports those events by 1/(1 - rate).
 * Separating the two readers needs an `openrouter` key, which requires that key
 * to exist in `CanonicalProvider` first.
 */

export type DiscountConfirmation = 'confirmed' | 'unconfirmed' | 'not-checkable'

/**
 * Corroborates the de-discount: where a model has both a promo route and an
 * undiscounted one, the recovered price should land on the sibling. Evidence
 * only, never a warning. Two hosts legitimately price the same open-weights
 * model differently, so a mismatch fires on half of all checkable models.
 */
export const confirmDiscountAgainstSiblings = (candidates: EndpointCandidate[]): DiscountConfirmation => {
    const discounted = candidates.filter((candidate) => candidate.discount > 0)
    const undiscounted = candidates.filter((candidate) => candidate.discount === 0)
    if (discounted.length === 0 || undiscounted.length === 0) {
        return 'not-checkable'
    }

    // Both sides already went through the same rounding, so exact equality holds.
    const siblingListPrices = new Set(undiscounted.map((candidate) => candidate.cost.prompt_token))
    return discounted.some((candidate) => siblingListPrices.has(candidate.cost.prompt_token))
        ? 'confirmed'
        : 'unconfirmed'
}

export interface DiscountReportEntry {
    model: string
    endpoints: Array<{ key: string; discount: number }>
    confirmation: DiscountConfirmation
}

/** Table rows rendered before the remainder collapses into a count line. */
export const DISCOUNT_REPORT_ROW_LIMIT = 200

/**
 * Model ids and endpoint tags are third-party strings from the OpenRouter
 * response, and this table becomes the body of a PR that approves a change to
 * the billing price book. Confine them to one cell: a newline or a pipe would
 * otherwise break the row apart, and angle brackets render as HTML on GitHub.
 */
export const sanitizeReportCell = (value: string): string =>
    value
        .replace(/[\r\n]+/g, ' ')
        .replace(/[|<>`]/g, '')
        .trim()
        .slice(0, 120)

/**
 * Renders promotions as explicit line items in the generated PR rather than as
 * unexplained price movements inside a large diff. `uncheckedModels` is
 * reported too: those prices may still carry a promotion, and a bare "no
 * discounts" would read as a verified negative rather than an unmeasured one.
 */
export const renderDiscountReport = (entries: DiscountReportEntry[], uncheckedModels = 0): string => {
    const unchecked =
        uncheckedModels > 0
            ? `\n${uncheckedModels} model(s) could not be checked (endpoint pricing unavailable); their prices may still carry a promotion.\n`
            : ''

    if (entries.length === 0) {
        return `## Discounts\n\nNo discounted endpoints found in this run.\n${unchecked}`
    }

    const rows = [...entries].sort((a, b) => a.model.localeCompare(b.model))
    const confirmed = rows.filter((row) => row.confirmation === 'confirmed').length
    const checkable = rows.filter((row) => row.confirmation !== 'not-checkable').length
    const endpointCount = rows.reduce((total, row) => total + row.endpoints.length, 0)

    const lines = [
        '## Discounts',
        '',
        `OpenRouter is running a promotion on **${endpointCount} endpoint(s)** across **${rows.length} model(s)**.`,
        'Per-provider keys below are stored at list rate, with the promotion divided back',
        'out, so a provider key keeps meaning what that provider charges a direct caller.',
        'The `default` key is left as OpenRouter serves it.',
        '',
        `Independently confirmed against an undiscounted sibling route: ${confirmed}/${checkable} checkable model(s).`,
        unchecked,
        '| Model | Endpoint | Rate | Confirmed |',
        '| --- | --- | --- | --- |',
    ]

    // Bounded on emitted rows rather than models: a model renders one row per
    // discounted endpoint, and the widest model in the catalogue carries 32 of
    // them, so a model cap does not bound the body GitHub has to accept.
    let emitted = 0
    let omittedModels = 0
    for (const row of rows) {
        if (emitted + row.endpoints.length > DISCOUNT_REPORT_ROW_LIMIT) {
            omittedModels += 1
            continue
        }
        for (const [index, endpoint] of row.endpoints.entries()) {
            const model = index === 0 ? sanitizeReportCell(row.model) : ''
            const confirmation = index === 0 ? row.confirmation : ''
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

const normalizeKeySegment = (raw: string): string =>
    raw
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')

const normalizeProviderKey = (endpoint: { tag?: string; provider_name?: string; name?: string }): string => {
    const rawKey = endpoint.tag || endpoint.provider_name || endpoint.name || 'unknown'
    return normalizeKeySegment(rawKey)
}

export interface BuiltModelRow {
    cost: Record<string, ModelCost>
    discount?: DiscountReportEntry
    /** False when no endpoint yielded usable pricing, so nothing was checked for promotions. */
    checked: boolean
}

/**
 * Turn one model's list-payload cost and its endpoints payload into the row that
 * gets written, plus whatever the discount report needs to say about it.
 *
 * Split out of the fetch loop so the wiring is reachable from a test: the
 * network call is the only part that has to be live.
 */
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

        const providerKey = normalizeProviderKey(endpoint)
        // The fallback is normalized too: any key here is also interpolated into
        // canonical-providers.ts as a string literal, so it has to be confined to
        // [a-z0-9-] by construction rather than by whatever the provider is named.
        const safeProviderKey =
            providerKey && providerKey !== 'default'
                ? providerKey
                : `provider-${normalizeKeySegment(endpoint.provider_name ?? 'unknown') || 'unknown'}`

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
                      endpoints: discounted.map(({ key, discount }) => ({ key, discount })),
                      confirmation: confirmDiscountAgainstSiblings(candidates),
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

/** Name of the env var carrying the summary path, shared with the workflow that sets it. */
export const DISCOUNT_SUMMARY_ENV = 'DISCOUNT_SUMMARY_PATH'

/**
 * Writes the run's outputs. The summary only decorates a PR body, so it goes
 * last and its failure is logged rather than thrown: a scratch-file problem
 * must not discard a completed run's fetching.
 */
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

const fetchOpenRouterCosts = async (): Promise<RunTotals> => {
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
    const models = data.data

    let totals: RunTotals = { models: [], discounts: [], uncheckedModels: 0 }

    for (const [modelIndex, model] of models.entries()) {
        if (!model?.id) {
            console.warn('Skipping model without id:', model)
            continue
        }

        // Gate before the endpoints request so an unpriceable model costs no
        // network call; buildModelRow re-derives the cost it validates here.
        if (!buildDefaultCost(model.pricing, model.id)) {
            console.warn('Skipping model without valid pricing:', model.id)
            continue
        }

        let endpoints: unknown[] = []

        const encodedModelId = model.id
            .split('/')
            .map((segment: string) => encodeURIComponent(segment))
            .join('/')

        try {
            console.log(`Fetching endpoint pricing for ${modelIndex + 1}/${models.length} ${model.id}...`)
            // eslint-disable-next-line no-restricted-globals
            const endpointRes = await fetch(`https://openrouter.ai/api/v1/models/${encodedModelId}/endpoints`, {})
            if (!endpointRes.ok) {
                console.warn(
                    `Failed to fetch endpoint pricing for ${model.id}: ${endpointRes.status} ${endpointRes.statusText}`
                )
            } else {
                let endpointsPayload
                try {
                    endpointsPayload = await endpointRes.json()
                } catch (parseError) {
                    console.warn('Failed to parse endpoint pricing payload for model:', model.id, parseError)
                }

                endpoints = endpointsPayload?.data?.endpoints ?? []
            }
        } catch (error) {
            console.warn('Error fetching endpoint pricing for model:', model.id, error)
        }

        const built = buildModelRow(model.id, model.pricing, endpoints)
        if (!built) {
            console.warn('Skipping model without valid pricing:', model.id)
            continue
        }
        totals = accumulateModelRow(built, model.id, totals)
    }

    const sortedModels = [...totals.models].sort((a, b) => a.model.localeCompare(b.model))

    if (totals.uncheckedModels > 0) {
        // Alias and meta-router models carry no per-endpoint pricing, so a
        // handful here is the steady state; aggregated to keep it readable.
        console.log(
            `${totals.uncheckedModels} model(s) had no usable endpoint pricing and were not checked for promotions`
        )
    }

    return { ...totals, models: sortedModels }
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
