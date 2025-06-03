import { Liquid } from 'liquidjs'

import { HogFunctionInvocationGlobalsWithInputs } from '../types'

const LIQUID_REGEX = /\{\{(.*?)\}\}|{%(.*?)%}/g

export class LiquidRenderer {
    private liquid: Liquid

    constructor() {
        this.liquid = new Liquid({
            strictFilters: false,
            strictVariables: false,
            outputEscape: 'escape',
        })

        // NOTE: We can register custom filters here if needed like below
        // this.liquid.registerFilter('default', (value: any, defaultValue: any) => value ?? defaultValue)
    }

    renderWithHogFunctionGlobals(template: string, globals: HogFunctionInvocationGlobalsWithInputs): Promise<string> {
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
                .replace(/&amp;/g, '&')
                .replace(/&quot;/g, '"')
                .replace(/&#x27;/g, "'")
        })

        return this.liquid.parseAndRenderSync(decodedTemplate, context)
    }
}

export const liquidRenderer = new LiquidRenderer()
