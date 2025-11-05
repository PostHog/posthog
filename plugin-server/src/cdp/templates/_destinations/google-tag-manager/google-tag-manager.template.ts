import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'site_destination',
    id: 'template-google-tag-manager',
    name: 'Google Tag Manager',
    description: 'Load Google Tag Manager within your website',
    icon_url: '/static/services/google-tag-manager.png',
    category: ['Custom'],
    code_language: 'javascript',
    code: `
// Adds window.dataLayer and lazily loads the Google Tag Manager script
function initSnippet(containerId) {
    (function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=!0;j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f)})(window,document,'script','dataLayer',containerId)
}

export async function onLoad({ inputs, posthog }) {
    initSnippet(inputs.containerId);
    
    if (posthog.config.debug) {
        console.log('[PostHog] Google Tag Manager init', inputs.containerId);
    }
}
export function onEvent({ inputs, posthog }) {
    if (posthog.config.debug) {
        console.log('[PostHog] Google Tag Manager track', inputs.containerId, inputs.payload);
    }
    dataLayer.push(inputs.payload);
}
`,
    inputs_schema: [
        {
            key: 'containerId',
            type: 'string',
            label: 'Container ID',
            secret: false,
            required: true,
            description:
                'You can find your Container ID in your [Accounts page](https://www.google.com/tagmanager/web/#management/Accounts/).',
            default: '',
        },
    ],
    mapping_templates: [
        {
            name: 'Pageview',
            include_by_default: true,
            filters: {
                events: [{ id: '$pageview', name: 'Pageview', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'payload',
                    type: 'dictionary',
                    label: 'payload',
                    default: {
                        event: '{event.event}',
                        title: '{event.properties.title}',
                        url: '{event.properties.$current_url}',
                    },
                    secret: false,
                    required: false,
                    description: 'Payload to send to Google Tag Manager.',
                },
            ],
        },
    ],
}
