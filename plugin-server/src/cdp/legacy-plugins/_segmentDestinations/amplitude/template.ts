import { HogFunctionInputSchemaType } from '~/src/cdp/types';
import { LegacyDestinationPlugin, LegacyDestinationPluginMeta } from '../../types'
import segmentDestination from './index'
import { ProcessedPluginEvent } from '@posthog/plugin-scaffold';
import { HogFunctionMappingTemplate } from '~/src/cdp/templates/types';

// NOTE: This is a deprecated plugin and should never be shown to new users

export const amplitudePlugin: LegacyDestinationPlugin = {
    onEvent: async (
        _event: ProcessedPluginEvent,
        { config, fetch, logger }: LegacyDestinationPluginMeta
    ): Promise<void> =>  {
        segmentDestination.actions.logEventV2.perform((endpoint, options) => {
            logger.warn('This is a test', { options })
            void fetch('https://webhook.site/1d50dcac-28d0-4b7b-95ed-0a2a3e26ab45', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${config.secretKey}`
                },
                body: JSON.stringify({ endpoint, options }),
            })
            return Promise.resolve({} as any)
        }, {
            payload: {
                userId: 'test-user-wxpys9',
                event: 'PostHog Test Event Name',
                properties: {
                    property1: 1,
                    property2: 'test',
                    property3: true
                }
            },
            settings: {
                apiKey: config.apiKey,
                endpoint: config.endpoint,
                secretKey: config.secretKey
            }
        })
    },
    template: {
        free: false,
        status: 'beta',
        type: 'destination',
        id: 'plugin-segment-amplitude',
        name: 'Amplitude (Segment)',
        description: 'Send event data to Amplitude',
        icon_url: 'https://raw.githubusercontent.com/rudderlabs/rudderstack-posthog-plugin/main/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: Object.entries(segmentDestination.authentication?.fields ?? { fallback: { label: 'Fallback', type: 'string', description: 'Fallback', default: 'fallback', required: true } }).map(([key, field]) => ({
            key,
            label: field.label,
            type: field.choices ? 'choice' : field.type ?? 'string',
            description: field.description,
            default: field.default ?? '',
            required: field.required ?? false,
            secret: false,
            ...(field.choices ? { choices: field.choices } : {}),
        })) as HogFunctionInputSchemaType[],
        mapping_templates: (segmentDestination.presets ?? []).map((preset) => ({
            name: preset.name,
            include_by_default: true,
            filters: {
                events: [
                    { id: '$pageview', name: 'Pageview', type: 'events' }
                ],
            },
            inputs_schema: Object.entries(segmentDestination.actions.logEventV2.fields ?? { fallback: { label: 'Fallback', type: 'string', description: 'Fallback', default: 'fallback', required: true } }).map(([key, field]) => ({
                key,
                label: field.label,
                type: field.choices ? 'choice'
                    : field.type === 'object' ? 'dictionary'
                    : ['number', 'integer', 'datetime'].includes(field.type) ? 'string'
                    : field.type ?? 'string',
                description: field.description,
                default: field.type !== 'object' ? JSON.stringify(field.default) ?? '' : Object.fromEntries(Object.entries(field.properties ?? {}).map(([key, _]) => {
                    const defaultVal = field.default as Record<string, object> ?? {}
                    return [key, JSON.stringify(defaultVal[key]) ?? '']
                })),
                required: field.required ?? false,
                secret: false,
                ...(field.choices ? { choices: field.choices } : {}),
            })) as HogFunctionInputSchemaType[],
        })) as HogFunctionMappingTemplate[]
    }
}
