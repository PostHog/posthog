// Lazy load liquid library
import { Context, Emitter, Liquid, Output, Tag, TagToken, Template, TopLevelToken } from 'liquidjs'

const LIQUID_TAG_CLOSERS: Record<string, string> = { '{': '}}', '%': '%}' }

// Copy of the currency filter in nodejs/src/cdp/utils/liquid.ts, so previews format money the way sends do.
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

// Copy of the tag in nodejs/src/cdp/utils/liquid.ts, so the editor accepts what the worker sends.
// Customer.io templates write the unsubscribe link as a tag, `{% unsubscribe_url %}`, where we expose a
// variable. The tag renders `{{ unsubscribe_url }}`, so it gets the same escaping as the variable and
// renders empty when the send has no unsubscribe URL.
class UnsubscribeUrlTag extends Tag {
    private readonly templates: Template[]

    constructor(token: TagToken, remainTokens: TopLevelToken[], liquid: Liquid) {
        super(token, remainTokens, liquid)
        this.templates = liquid.parse('{{ unsubscribe_url }}')
    }

    *render(ctx: Context, emitter: Emitter): Generator<unknown, void, unknown> {
        yield this.liquid.renderer.renderTemplates(this.templates, ctx, emitter)
    }
}

// NOTE: This should be moved to common package but currently is a copy of nodejs/src/cdp/utils/liquid.ts
export class LiquidRenderer {
    private static _liquid: Liquid | null = null

    private static get liquid(): Liquid {
        if (!this._liquid) {
            this._liquid = new Liquid({
                outputEscape: 'escape',
                // Render partials from an in-memory map only: this disables LiquidJS's filesystem-backed
                // partial loading, so user-controlled templates can't read local files via include/render/layout.
                templates: {},
            })
            this._liquid.registerFilter('currency', formatCurrency)
            this._liquid.registerTag('unsubscribe_url', UnsubscribeUrlTag)
        }
        return this._liquid
    }

    private static decodeEntities(source: string): string {
        return source
            .replace(/&lt;/g, '<')
            .replace(/&gt;/g, '>')
            .replace(/&quot;/g, '"')
            .replace(/&#x27;/g, "'")
            .replace(/&amp;/g, '&') // NOTE: This should always be last
    }

    // TRICKY: Unlayer replaces all liquid's elements like > for example with &gt;
    // We need to decode these but _only_ for the liquid elements i.e. content within {{ }} or {% %}
    // Copy of decodeLiquidTags in nodejs/src/cdp/utils/liquid.ts: a single forward pass, so a tag can span
    // lines without a regex rescanning the rest of the template for every unclosed opener.
    private static decode(template: string): string {
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
            out += template.slice(cursor, open) + this.decodeEntities(template.slice(open, close + 2))
            cursor = close + 2
        }

        return out + template.slice(cursor)
    }

    public static parse(template: string): Template[] {
        return this.liquid.parse(this.decode(template))
    }

    /** Mirrors what the worker renders at send time. Throws on an unparseable template. */
    public static render(template: string, context: Record<string, any>): string {
        return this.liquid.parseAndRenderSync(this.decode(template), context)
    }

    /**
     * Takes the expression as it appears in the template, so it decodes the editor's escaping first.
     */
    public static resolves(expression: string, context: Record<string, any>): boolean {
        return this.resolvesDecoded(this.decodeEntities(expression), context)
    }

    private static resolvesDecoded(expression: string, context: Record<string, any>): boolean {
        try {
            const value = this.liquid.evalValueSync(expression, context)
            return value !== undefined && value !== null
        } catch {
            return false
        }
    }

    /**
     * Render, but leave an output tag whose expression resolves to nothing as its own source text
     * instead of the empty string a plain render produces, so a reader sees which variables are
     * missing rather than a blank space.
     *
     * An expression carrying a filter renders normally, because the filter may be the fallback
     * (`| default:`), so an undefined value there is not necessarily a gap.
     *
     * Additive to the worker's copy of this class, which only ever renders the real thing.
     */
    public static renderKeepingUnresolved(template: string, context: Record<string, any>): string {
        const decoded = this.decode(template)
        let marked = ''
        let cursor = 0
        for (const node of this.liquid.parse(decoded)) {
            if (!(node instanceof Output)) {
                continue
            }
            const { begin, end, content } = node.token as unknown as { begin: number; end: number; content: string }
            const expression = content.trim()
            if (!expression || expression.includes('|') || this.resolvesDecoded(expression, context)) {
                continue
            }
            marked += `${decoded.slice(cursor, begin)}{% raw %}${decoded.slice(begin, end)}{% endraw %}`
            cursor = end
        }
        // `marked` is already decoded, so render it without a second pass.
        return this.liquid.parseAndRenderSync(marked + decoded.slice(cursor), context)
    }
}
