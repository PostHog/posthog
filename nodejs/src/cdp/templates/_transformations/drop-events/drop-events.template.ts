import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-drop-events',
    name: 'Drop Events',
    description: 'Drop events based on defined filters.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
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
