import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

export const phShotgunProcessEventApp: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-ph-shotgun-processevent-app',
        name: 'Shotgun Process Event App',
        description: 'Process Shotgun events',
        icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
        category: ['Transformation'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
