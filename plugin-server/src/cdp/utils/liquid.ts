import { Liquid } from 'liquidjs'

import { HogFunctionInvocationGlobalsWithInputs } from '../types'

export class LiquidRenderer {
    private liquid: Liquid

    constructor() {
        this.liquid = new Liquid({
            strictFilters: false,
            strictVariables: false,
            outputEscape: 'escape',
        })

        // Register custom filters
        this.liquid.registerFilter('default', (value: any, defaultValue: any) => value ?? defaultValue)
        this.liquid.registerFilter('date', (value: any, format: string) => {
            // Handle "now" as current date
            const date = value === 'now' ? new Date() : new Date(value)

            // Simple date formatting - you can expand this
            if (format === '%Y%m%d') {
                return (
                    date.getFullYear().toString() +
                    (date.getMonth() + 1).toString().padStart(2, '0') +
                    date.getDate().toString().padStart(2, '0')
                )
            }
            if (format === '%B %-d, %Y at %l:%M %p') {
                return (
                    date.toLocaleDateString('en-US', {
                        month: 'long',
                        day: 'numeric',
                        year: 'numeric',
                    }) +
                    ' at ' +
                    date.toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        minute: '2-digit',
                        hour12: true,
                    })
                )
            }
            if (format === '%l:%M %p') {
                return date.toLocaleTimeString('en-US', {
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true,
                })
            }
            // Fallback to ISO string
            return date.toISOString()
        })
    }

    private async render(template: string, context: any): Promise<string> {
        // TODO: BW - understand this better.
        // HTML decode the template before processing. To do maybe we should use a library for better html decoding
        // $ is not decoded because it is used as a variable in liquid templates, so we need to handle this separately

        const decodedTemplate = template
            .replace(/&gt;/g, '>')
            .replace(/&lt;/g, '<')
            .replace(/&amp;/g, '&')
            .replace(/&quot;/g, '"')
            .replace(/&#x27;/g, "'")

        return await this.liquid.parseAndRender(decodedTemplate, context)
    }

    async renderWithHogFunctionGlobals(
        template: string,
        globals: HogFunctionInvocationGlobalsWithInputs
    ): Promise<string> {
        const context = {
            event: globals.event,
            person: globals.person,
            groups: globals.groups,
            project: globals.project,
            source: globals.source,
            inputs: globals.inputs || {},
            now: new Date(),
        }
        return await this.render(template, context)
    }
}
