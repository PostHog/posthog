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
