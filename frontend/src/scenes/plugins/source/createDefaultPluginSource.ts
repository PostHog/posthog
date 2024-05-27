export const createDefaultPluginSource = (name: string): Record<string, any> => ({
    'index.ts': `// Learn more about plugins at: https://posthog.com/docs/apps/build

// Processes each event, optionally transforming it
export function processEvent(event, { config }) {
    // Some events (such as $identify) don't have properties
    if (event.properties) {
        event.properties['hello'] = \`Hello \${config.name}\`
    }
    // Return the event to be ingested, or return null to discard
    return event
}

// Runs when the plugin is loaded, allows for preparing it as needed
export function setupPlugin (meta) {
    console.log(\`The date is \${new Date().toDateString()}\`)
}`,
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
}
`,
    'plugin.json': JSON.stringify(
        {
            name: name ?? 'My Plugin',
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
    'site.ts': "export function inject({ config, posthog }) {\n    console.log('Hello from PostHog-JS')\n}\n",
})
