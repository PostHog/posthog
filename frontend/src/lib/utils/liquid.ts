// Lazy load liquid library
import { Liquid, Template } from 'liquidjs'

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

    /** Render a template the way the worker does at send time. Throws on an unparseable template. */
    public static render(template: string, context: Record<string, any>): string {
        return this.liquid.parseAndRenderSync(this.decode(template), context)
    }

    /**
     * Whether an expression such as `person.properties.email` has a value in this context. Takes
     * the expression as it appears in the template, so it decodes the editor's escaping first.
     */
    public static resolves(expression: string, context: Record<string, any>): boolean {
        try {
            const value = this.liquid.evalValueSync(this.decodeEntities(expression), context)
            return value !== undefined && value !== null
        } catch {
            return false
        }
    }
}
