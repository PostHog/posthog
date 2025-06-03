import { Liquid } from 'liquidjs'

import { logger } from '../../utils/logger'

export const parseLiquidTemplate = (
    template: string,
    context: any,
    inputs?: Record<string, any>,
    allowLiquid: boolean = false
): string => {
    // Early return if liquid processing is disabled
    if (!allowLiquid) {
        logger.info('🔍 Liquid parsing disabled', { template, allowLiquid })
        return template
    }

    try {
        const liquid = new Liquid({
            strictFilters: false,
            strictVariables: false,
            outputEscape: 'escape',
        })

        // Register custom filters
        liquid.registerFilter('default', (value: any, defaultValue: any) => value ?? defaultValue)
        liquid.registerFilter('date', (value: any, format: string) => {
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

        // HTML decode the template before processing. To do maybe we should use a library for better html decoding
        // $ is not decoded because it is used as a variable in liquid templates, so we need to handle this separately
        const decodedTemplate = template
            .replace(/&gt;/g, '>')
            .replace(/&lt;/g, '<')
            .replace(/&amp;/g, '&')
            .replace(/&quot;/g, '"')
            .replace(/&#x27;/g, "'")

        const liquidContext = {
            event: context.event,
            person: context.person,
            groups: context.groups,
            project: context.project,
            source: context.source,
            inputs: inputs || {},
            now: new Date(),
        }

        const result = liquid.parseAndRenderSync(decodedTemplate, liquidContext)

        return result
    } catch (error) {
        logger.warn('🔍 Liquid template parsing failed', {
            error: error.message,
            template,
            stack: error.stack,
        })
        return template
    }
}
