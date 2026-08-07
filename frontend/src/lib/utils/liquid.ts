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
            })
        }
        return this._liquid
    }

    public static parse(template: string): Template[] {
        // TRICKY: Unlayer replaces all liquid's elements like > for example with &gt;
        // We need to decode these but _only_ for the liquid elements i.e. content within {{ }} or {% %}
        const decodedTemplate = template.replace(LIQUID_REGEX, (match) => {
            return match
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>')
                .replace(/&quot;/g, '"')
                .replace(/&#x27;/g, "'")
                .replace(/&amp;/g, '&') // NOTE: This should always be last
        })

        return this.liquid.parse(decodedTemplate)
    }
}

// LiquidJS reads a `$` that follows a dot as the start of a filter, so a `$`-prefixed property in a
// dotted path (e.g. `event.properties.$set.email`) fails to parse with a cryptic "expected '|'"
// message. Bracket notation is the supported way to reach such keys.
const DOLLAR_PREFIXED_KEY_IN_PATH = /\.\$/

// Parse a Liquid template and return a human-readable error if it fails, or undefined if it parses.
// When the failure is the `$`-in-dotted-path case, point the author at the bracket-notation fix.
export function getLiquidTemplateError(template: string): string | undefined {
    try {
        LiquidRenderer.parse(template)
    } catch (e: any) {
        let error = `Liquid template error: ${e.message}`
        if (DOLLAR_PREFIXED_KEY_IN_PATH.test(template)) {
            error += `. Property names starting with $ need bracket notation, for example event.properties["$set"]["email"] instead of event.properties.$set.email`
        }
        return error
    }
}
