// Lazy load liquid library
import { Liquid, Output, Template } from 'liquidjs'

const LIQUID_REGEX = /\{\{(.*?)\}\}|{%(.*?)%}/g

// NOTE: This should be moved to common package but currently is a copy of plugin-server/src/cdp/utils/liquid.ts
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
    private static decode(template: string): string {
        return template.replace(LIQUID_REGEX, (match) => this.decodeEntities(match))
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
