import { HogFunctionInputSchemaType } from '~/src/cdp/types';
import { LegacyDestinationPlugin, LegacyDestinationPluginMeta } from '../../types'
import segmentDestination from './index'
import { ProcessedPluginEvent } from '@posthog/plugin-scaffold';

// NOTE: This is a deprecated plugin and should never be shown to new users

export const amplitudePlugin: LegacyDestinationPlugin = {
    onEvent: async (
        _event: ProcessedPluginEvent,
        { config, fetch }: LegacyDestinationPluginMeta
    ): Promise<void> =>  {
        await fetch('https://webhook.site/1d50dcac-28d0-4b7b-95ed-0a2a3e26ab45', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ok: 'yeah' }),
        })
    },
    template: {
        free: false,
        status: 'beta',
        type: 'destination',
        id: 'segment-amplitude',
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
        })) as HogFunctionInputSchemaType[]
    },
}
