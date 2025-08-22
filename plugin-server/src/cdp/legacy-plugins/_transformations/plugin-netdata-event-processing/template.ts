import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from './dist'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const pluginNetdataEventProcessing: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-plugin-netdata-event-processing',
        name: 'Netdata Event Processing',
        description: 'Event processing for Netdata',
        icon_url: '/static/hedgehog/builder-hog-01.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
