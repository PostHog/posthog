import { Liquid } from 'liquidjs'

import { HogFunctionInvocationGlobalsWithInputs } from '../types'

const LIQUID_REGEX = /\{\{(.*?)\}\}|{%(.*?)%}/g

// Rendering is synchronous on shared multi-tenant workers, so an unbounded template would
// stall or OOM the whole process. These budgets make an over-budget template fail only its own invocation.
const LIQUID_PARSE_LIMIT_CHARS = 100_000
const LIQUID_RENDER_LIMIT_MS = 500
const LIQUID_MEMORY_LIMIT_UNITS = 1_000_000

export class LiquidRenderer {
    private static _liquid: Liquid | null = null

    private static get liquid(): Liquid {
        if (!this._liquid) {
            this._liquid = new Liquid({
                outputEscape: 'escape',
                // Render partials from an in-memory map only: this disables LiquidJS's filesystem-backed
                // partial loading, so user-controlled templates can't read local files via include/render/layout.
                templates: {},
                parseLimit: LIQUID_PARSE_LIMIT_CHARS,
                renderLimit: LIQUID_RENDER_LIMIT_MS,
                memoryLimit: LIQUID_MEMORY_LIMIT_UNITS,
            })
        }
        return this._liquid
    }

    static renderWithHogFunctionGlobals(template: string, globals: HogFunctionInvocationGlobalsWithInputs): string {
        const context = {
            ...globals,
            now: new Date(),
        }

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

        return this.liquid.parseAndRenderSync(decodedTemplate, context)
    }
}
