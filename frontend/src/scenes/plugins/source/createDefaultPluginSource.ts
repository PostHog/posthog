export const createDefaultPluginSource = (name: string): Record<string, any> => ({
    'index.ts': `// Learn more about plugins at: https://posthog.com/docs/plugins/build/overview

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
}

// Runs every hour on the hour
export async function runEveryHour(meta) {
    const response = await fetch('https://palabras-aleatorias-public-api.herokuapp.com/random')
    const data = await response.json()
    const randomSpanishWord = data.body.Word
    console.log(\`¡\${randomSpanishWord.toUpperCase()}!\`)
}`,
    'plugin.json': JSON.stringify(
        {
            name,
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
})
