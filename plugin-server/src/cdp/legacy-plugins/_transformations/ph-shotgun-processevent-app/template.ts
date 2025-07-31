import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from '.'

export const phShotgunProcessEventApp: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-ph-shotgun-processevent-app',
        name: 'Shotgun Process Event App',
        description: 'Process Shotgun events',
        icon_url: '/static/hedgehog/builder-hog-01.png',
        category: ['Transformation'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
