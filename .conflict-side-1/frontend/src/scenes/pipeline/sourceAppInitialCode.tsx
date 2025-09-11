export enum SourcePluginKind {
    FilterEvent = 'filterEvent',
    ModifyEvent = 'modifyEvent',
    ComposeWebhook = 'composeWebhook',
    Site = 'site',
    Frontend = 'frontend',
}

export function getInitialCode(name: string, kind: SourcePluginKind): Record<string, any> {
    switch (kind) {
        case SourcePluginKind.FilterEvent:
            return {
                'plugin.json': JSON.stringify(
                    {
                        name: name,
                        config: [
                            {
                                markdown: 'Specify your config here',
                            },
                            {
                                key: 'eventToSkip',
                                name: 'Event to skip',
                                type: 'string',
                                hint: 'If the event name matches this, it will be skipped',
                                default: '$pageview',
                                required: false,
                            },
                        ],
                    },
                    null,
                    4
                ),
                'index.ts': `// Learn more about plugins at: https://posthog.com/docs/apps/build

// Processes each event, optionally dropping it
export function processEvent(event, { config }) {
    if (event.event === config.eventToSkip) {
        return null
    }
    return event
}

// Runs when the plugin is loaded, allows for preparing it as needed
export function setupPlugin (meta) {
    console.log(\`The date is \${new Date().toDateString()}\`)
}`,
            }
        case SourcePluginKind.ModifyEvent:
            return {
                'plugin.json': JSON.stringify(
                    {
                        name: name,
                        config: [
                            {
                                markdown: 'Specify your config here',
                            },
                            {
                                key: 'propertyToRemove',
                                name: 'Property to remove',
                                type: 'string',
                                hint: 'This property will be removed from all events',
                                default: '$browser',
                                required: false,
                            },
                        ],
                    },
                    null,
                    4
                ),
                'index.ts': `// Learn more about plugins at: https://posthog.com/docs/apps/build

// Processes each event, optionally modify it
export function processEvent(event, { config }) {
    event.properties[config.propertyToRemove] = undefined
    return event
}

// Runs when the plugin is loaded, allows for preparing it as needed
export function setupPlugin (meta) {
    console.log(\`The date is \${new Date().toDateString()}\`)
}`,
            }
        case SourcePluginKind.ComposeWebhook:
            return {
                'plugin.json': JSON.stringify(
                    {
                        name: name,
                        config: [
                            {
                                markdown: 'Specify your config here',
                            },
                            {
                                key: 'url',
                                name: 'The destination url',
                                type: 'string',
                                hint: 'Where the webhook will be sent to',
                                default: '',
                                required: true,
                            },
                        ],
                    },
                    null,
                    4
                ),
                'index.ts': `// Learn more about plugins at: https://posthog.com/docs/apps/build
import { PostHogEvent, Webhook } from '@posthog/plugin-scaffold'

export function composeWebhook(event: PostHogEvent, { config }: any): Webhook {
    return {
        url: config.url,
        body: JSON.stringify(event),
        headers: {
            'Content-Type': 'application/json',
        },
        method: 'POST',
    }
}`,
            }
        case SourcePluginKind.Site:
            return {
                'plugin.json': JSON.stringify(
                    {
                        name: name,
                        config: [
                            {
                                markdown: 'Specify your config here',
                            },
                            {
                                key: 'name',
                                name: 'Person to greet',
                                type: 'string',
                                hint: 'Used to personalise the property `hello`',
                                default: 'world',
                                required: false,
                            },
                        ],
                    },
                    null,
                    4
                ),
                'site.ts': `export function inject({ config, posthog }) {\n    console.log('Hello from PostHog-JS')\n}\n"`,
            }
        case SourcePluginKind.Frontend:
            return {
                'plugin.json': JSON.stringify(
                    {
                        name: name,
                        config: [
                            {
                                markdown: 'Specify your config here',
                            },
                            {
                                key: 'name',
                                name: 'Person to greet',
                                type: 'string',
                                hint: 'Used to personalise the property `hello`',
                                default: 'world',
                                required: false,
                            },
                        ],
                    },
                    null,
                    4
                ),
                'frontend.tsx': `import React from "react"

                export const scene = {
                    title: "My Stuff",
                    component: function MyStuff({ config }) {
                        return (
                            <div>
                                <h1>My Favourite Links</h1>
                                <ul>
                                    <li>
                                        <a href="https://news.ycombinator.com">The NEWS</a>
                                    </li>
                                </ul>
                                <h1>My Favourite Cow</h1>
                                <img src="https://media.giphy.com/media/RYKFEEjtYpxL2/giphy.gif" />
                            </div>
                        )
                    },
                }`,
            }
    }
}
