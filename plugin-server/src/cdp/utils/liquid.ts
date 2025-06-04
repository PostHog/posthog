import { Liquid } from 'liquidjs'

import { HogFunctionInvocationGlobalsWithInputs } from '../types'

const LIQUID_REGEX = /\{\{(.*?)\}\}|{%(.*?)%}/g

export class LiquidRenderer {
    private static _liquid: Liquid | null = null

    private static get liquid(): Liquid {
        if (!this._liquid) {
            this._liquid = new Liquid({
                strictFilters: false,
                strictVariables: false,
                outputEscape: 'escape',
            })
        }
        return this._liquid
    }

    static renderWithHogFunctionGlobals(template: string, globals: HogFunctionInvocationGlobalsWithInputs): string {
        const context = {
            event: globals.event,
            person: globals.person,
            groups: globals.groups,
            project: globals.project,
            source: globals.source,
            inputs: globals.inputs || {},
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
