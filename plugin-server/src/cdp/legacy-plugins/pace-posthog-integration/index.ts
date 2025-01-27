import { Plugin, Webhook } from '@posthog/plugin-scaffold'

export interface PaceMetaInput {
    config: {
        api_key: string
    }
}

const plugin: Plugin<PaceMetaInput> = {
    composeWebhook: (event, { config }) =>
        ({
            url: 'https://data.production.paceapp.com/events',
            headers: {
                'Content-Type': 'application/json',
                'x-api-key': config.api_key,
            },
            body: JSON.stringify({
                data: {
                    ...event,
                    properties: Object.fromEntries(
                        Object.entries(event.properties || {}).filter(([key, _]) => !key.startsWith('$'))
                    ),
                },
            }),
            method: 'POST',
        } as Webhook),
}

export default plugin
