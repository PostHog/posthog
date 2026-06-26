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
        icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
