import { LegacyTransformationPlugin } from '../../types'
import { setupPlugin } from './index'

export const firstTimeEventTrackerPlugin: LegacyTransformationPlugin = {
    setupPlugin,
    // NOTE: This is a special case where the processEvent is not actually run.
    processEvent: (event) => event,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-first-time-event-tracker',
        name: 'Flatten Properties',
        description:
            'This plugin will flatten all nested properties into a single property. You will not be billed for any events that this plugin drops.',
        icon_url: 'https://raw.githubusercontent.com/posthog/flatten-properties-plugin/main/logo.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                key: 'events',
                label: 'List of events to track first time occurrences on:',
                type: 'string',
                default: '',
                description: 'Separate events with commas, without using spaces, like so: `event1,event2,event3`',
                required: true,
            },
            {
                key: 'legacy_plugin_config_id',
                label: 'Legacy plugin config ID',
                description: 'The ID of the legacy plugin config that this was migrated from. (DO NOT MODIFY THIS)',
                type: 'string',
                default: '',
                required: true,
            },
        ],
    },
}
