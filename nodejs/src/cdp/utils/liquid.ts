import { Liquid } from 'liquidjs'

import { rowScopedTriggerTypeForEvent } from '../schema/hogflow'
import { HogFunctionInvocationGlobalsWithInputs } from '../types'

// Rendering is synchronous on shared multi-tenant workers, so an unbounded template would
// stall or OOM the whole process. These budgets make an over-budget template fail only its own invocation.
// Length is a weak proxy for render cost: real email bodies reach megabytes because a logo is inlined
// as a base64 data URI, while carrying only a handful of tags. Time and memory are what bound the work,
// so the length caps sit above the largest legitimate template rather than near the typical one.
const LIQUID_PARSE_LIMIT_CHARS = 5_000_000
// Charged only for values the template constructs (ranges, joins, padding, string filters), so literal
// passthrough of a large body is free and this still catches expansion.
const LIQUID_MEMORY_LIMIT_UNITS = 1_000_000
// Time and output are budgeted per invocation, not per template, because one invocation renders
// every string leaf of every liquid input and those leaves would otherwise each get a full budget.
const LIQUID_RENDER_LIMIT_MS = 500
const LIQUID_OUTPUT_LIMIT_CHARS = 10_000_000

const LIQUID_TAG_CLOSERS: Record<string, string> = { '{': '}}', '%': '%}' }

// These filters evaluate a tenant-written expression once per array item and LiquidJS only checks
// the render deadline between template nodes, so one filter call can run unbounded. They are replaced
// with a throwing filter rather than unregistered, because an unknown filter silently acts as identity.
const LIQUID_UNBOUNDED_FILTERS = ['where_exp', 'find_exp', 'find_index_exp', 'reject_exp', 'group_by_exp']

export class LiquidRenderBudget {
    private usedMs = 0
    private outputChars = 0

    remainingMs(): number {
        return Math.max(0, LIQUID_RENDER_LIMIT_MS - this.usedMs)
    }

    useTime(ms: number): void {
        this.usedMs += ms
    }

    useOutput(chars: number): void {
        this.outputChars += chars
        if (this.outputChars > LIQUID_OUTPUT_LIMIT_CHARS) {
            throw new Error(`liquid output limit exceeded (${LIQUID_OUTPUT_LIMIT_CHARS} characters per invocation)`)
        }
    }
}

const decodeEntities = (tag: string): string => {
    return tag
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#x27;/g, "'")
        .replace(/&amp;/g, '&') // NOTE: This should always be last
}

// TRICKY: Unlayer replaces all liquid's elements like > for example with &gt;
// We need to decode these but _only_ for the liquid elements i.e. content within {{ }} or {% %}
// This is a single forward pass: a regex with a lazy `.*?` rescans to the end of the line for every
// unmatched opener, which is quadratic on tenant-controlled input.
const decodeLiquidTags = (template: string): string => {
    let out = ''
    let cursor = 0
    const exhausted = new Set<string>()

    while (cursor < template.length) {
        const open = template.indexOf('{', cursor)
        if (open === -1) {
            break
        }
        const closer = LIQUID_TAG_CLOSERS[template[open + 1]]
        const close = closer && !exhausted.has(closer) ? template.indexOf(closer, open + 2) : -1
        if (close === -1) {
            if (closer) {
                exhausted.add(closer)
            }
            out += template.slice(cursor, open + 1)
            cursor = open + 1
            continue
        }
        out += template.slice(cursor, open) + decodeEntities(template.slice(open, close + 2))
        cursor = close + 2
    }

    return out + template.slice(cursor)
}

// The currency a locale implies when a template names only a locale, as in `currency: "en-GB"`.
const REGION_CURRENCIES: Record<string, string> = {
    US: 'USD',
    GB: 'GBP',
    CA: 'CAD',
    AU: 'AUD',
    NZ: 'NZD',
    IN: 'INR',
    JP: 'JPY',
    CH: 'CHF',
    SE: 'SEK',
    NO: 'NOK',
    DK: 'DKK',
    PL: 'PLN',
    BR: 'BRL',
    MX: 'MXN',
    ...Object.fromEntries(
        ['AT', 'BE', 'DE', 'ES', 'FI', 'FR', 'GR', 'IE', 'IT', 'LU', 'NL', 'PT'].map((region) => [region, 'EUR'])
    ),
}

// The languages a locale argument may name, with the region a bare language implies.
const LANGUAGE_REGIONS: Record<string, string> = {
    en: 'US',
    fr: 'FR',
    de: 'DE',
    es: 'ES',
    it: 'IT',
    nl: 'NL',
    pt: 'PT',
    fi: 'FI',
    sv: 'SE',
    da: 'DK',
    nb: 'NO',
    no: 'NO',
    pl: 'PL',
    ja: 'JP',
}
const LOCALE_ARGUMENT = /^([a-z]{2})(?:[-_]([a-z]{2}))?$/i
const CURRENCY_CODE = /^[a-z]{3}$/i

// Customer.io's `currency` takes `locale, code` (`"en", "EUR"`) or a locale alone (`"en-GB"`), and
// templates also pass a bare ISO code (`"USD"`), so all three forms resolve to a locale and a code.
// Arguments are checked against fixed patterns and tables, never parsed with Intl.Locale: a filter
// call runs to completion before the render deadline is checked, and exotic locale tags are slow to parse.
const resolveCurrencyFormat = (first: unknown, second: unknown): [string, string] | null => {
    if (first === undefined) {
        return ['en-US', 'USD']
    }
    if (typeof first !== 'string' || (second !== undefined && typeof second !== 'string')) {
        return null
    }
    if (second === undefined && CURRENCY_CODE.test(first)) {
        return ['en-US', first.toUpperCase()]
    }
    const locale = LOCALE_ARGUMENT.exec(first)
    const language = locale?.[1].toLowerCase()
    if (!locale || !language || !LANGUAGE_REGIONS[language]) {
        return null
    }
    const region = (locale[2] ?? LANGUAGE_REGIONS[language]).toUpperCase()
    const code =
        second === undefined ? REGION_CURRENCIES[region] : CURRENCY_CODE.test(second) ? second.toUpperCase() : null
    return code ? [`${language}-${region}`, code] : null
}

// Building a formatter costs far more than using one, so templates that repeat their arguments reuse it.
// Cleared when full, so tenant-chosen arguments can't grow it without bound.
const CURRENCY_FORMATTER_CACHE_LIMIT = 256
const currencyFormatters = new Map<string, Intl.NumberFormat | null>()

const currencyFormatter = (first: unknown, second: unknown): Intl.NumberFormat | null => {
    const format = resolveCurrencyFormat(first, second)
    if (!format) {
        return null
    }
    const key = format.join(' ')
    let formatter = currencyFormatters.get(key)
    if (formatter === undefined) {
        try {
            formatter = new Intl.NumberFormat(format[0], { style: 'currency', currency: format[1] })
        } catch {
            formatter = null
        }
        if (currencyFormatters.size >= CURRENCY_FORMATTER_CACHE_LIMIT) {
            currencyFormatters.clear()
        }
        currencyFormatters.set(key, formatter)
    }
    return formatter
}

// A value that isn't a number, or arguments that don't resolve, pass through unchanged, so a bad value
// stays visible instead of turning into "$0.00".
const formatCurrency = (value: unknown, first?: unknown, second?: unknown): unknown => {
    const amount = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
    if (!Number.isFinite(amount)) {
        return value
    }
    return currencyFormatter(first, second)?.format(amount) ?? value
}

const createLiquid = (outputEscape: 'escape' | undefined): Liquid => {
    const liquid = new Liquid({
        outputEscape,
        // Render partials from an in-memory map only: this disables LiquidJS's filesystem-backed
        // partial loading, so user-controlled templates can't read local files via include/render/layout.
        templates: {},
        parseLimit: LIQUID_PARSE_LIMIT_CHARS,
        renderLimit: LIQUID_RENDER_LIMIT_MS,
        memoryLimit: LIQUID_MEMORY_LIMIT_UNITS,
    })
    for (const name of LIQUID_UNBOUNDED_FILTERS) {
        liquid.registerFilter(name, () => {
            throw new Error(`liquid filter ${name} is not supported`)
        })
    }
    liquid.registerFilter('currency', formatCurrency)
    return liquid
}

export type LiquidRenderOptions = {
    // Only for output that is never parsed as HTML, such as an email subject or its plain-text part.
    escapeHtml?: boolean
}

export class LiquidRenderer {
    private static _liquid: Liquid | null = null
    private static _plainTextLiquid: Liquid | null = null

    private static get liquid(): Liquid {
        return (this._liquid ??= createLiquid('escape'))
    }

    private static get plainTextLiquid(): Liquid {
        return (this._plainTextLiquid ??= createLiquid(undefined))
    }

    static renderWithHogFunctionGlobals(
        template: string,
        globals: HogFunctionInvocationGlobalsWithInputs,
        budget: LiquidRenderBudget = new LiquidRenderBudget(),
        { escapeHtml = true }: LiquidRenderOptions = {}
    ): string {
        // Checked before decoding so the decoder never sees a string LiquidJS would reject anyway.
        if (template.length > LIQUID_PARSE_LIMIT_CHARS) {
            throw new Error(`liquid parse length limit exceeded (${LIQUID_PARSE_LIMIT_CHARS} characters)`)
        }

        // A warehouse row arrives under `event.properties`, and `record` is the alias the trigger
        // panel tells people to write. A hog-templated input gets that alias rewritten at save time,
        // but a liquid-templated input renders here, so the alias has to exist in the context.
        const isWarehouseRow = rowScopedTriggerTypeForEvent(globals.event?.event) !== null

        const context = {
            ...globals,
            now: new Date(),
            ...(isWarehouseRow ? { record: globals.event?.properties ?? {} } : {}),
        }

        const start = performance.now()
        try {
            const liquid = escapeHtml ? this.liquid : this.plainTextLiquid
            const result: string = liquid.parseAndRenderSync(decodeLiquidTags(template), context, {
                renderLimit: budget.remainingMs(),
            })
            // String length is O(1) on a V8 rope, so this rejects a huge result before anything flattens it.
            budget.useOutput(result.length)
            return result
        } finally {
            budget.useTime(performance.now() - start)
        }
    }
}
