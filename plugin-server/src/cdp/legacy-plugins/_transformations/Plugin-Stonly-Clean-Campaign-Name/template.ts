import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const pluginStonlyCleanCampaignName: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-Plugin-Stonly-Clean-Campaign-Name',
        name: 'Clean Campaign Name',
        description: 'Clean campaign name',
        icon_url: '/static/hedgehog/builder-hog-01.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
