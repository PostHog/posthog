import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-drop-events',
    name: 'Drop Events',
    description: 'Drop events based on defined filters.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
return null`,
    inputs_schema: [],
    filters: {
        events: [
            {
                id: 'CHANGE-ME',
                name: 'CHANGE-ME',
                type: 'events',
                order: 0,
            },
        ],
    },
}
