import { afterMount, defaults, kea, key, listeners, path, props } from 'kea'

import type { pluginSourceLogicType } from './pluginSourceLogicType'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { validateJson } from 'lib/utils'

interface PluginSourceProps {
    id: number
}

interface PluginSourceSlice {
    name: string
    source: string
    source_frontend: string
    config_schema: string
}

const defaultSource = `// Learn more about plugins at: https://posthog.com/docs/plugins/build/overview

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
async function runEveryHour(meta) {
    const response = await fetch('https://palabras-aleatorias-public-api.herokuapp.com/random')
    const data = await response.json()
    const randomSpanishWord = data.body.Word
    console.log(\`¡\${randomSpanishWord.toUpperCase()}!\`)
}`

const defaultConfig = [
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
]

export const pluginSourceLogic = kea<pluginSourceLogicType<PluginSourceProps, PluginSourceSlice>>([
    path(['scenes', 'plugins', 'edit', 'pluginSourceLogic']),
    props({} as PluginSourceProps),
    key((props) => props.id),

    defaults({
        plugin: {
            name: '',
            source: defaultSource,
            source_frontend: '',
            config_schema: JSON.stringify(defaultConfig, null, 2),
        } as PluginSourceSlice,
    }),

    forms(({ props, values }) => ({
        plugin: {
            errors: ({ name, config_schema }) => ({
                name: !name ? 'Please enter a name' : '',
                config_schema: !validateJson(config_schema) ? 'Not valid JSON' : '',
            }),
            submit: async () => {
                const { plugin } = values
                const response = await api.update(`api/organizations/@current/plugins/${props.id}`, {
                    name: plugin.name,
                    source: plugin.source,
                    source_frontend: plugin.source_frontend,
                    config_schema: JSON.parse(plugin.config_schema),
                })
                return {
                    name: response.name,
                    source: response.source,
                    source_frontend: response.source_frontend,
                    config_schema: JSON.stringify(response.config_schema, null, 2),
                }
            },
        },
    })),

    loaders(({ props }) => ({
        plugin: {
            getPlugin: async () => {
                const response = await api.get(`api/organizations/@current/plugins/${props.id}`)
                return {
                    name: response.name,
                    source: response.source,
                    source_frontend: response.source_frontend,
                    config_schema: JSON.stringify(response.config_schema, null, 2),
                }
            },
        },
    })),

    afterMount(({ actions }) => {
        actions.getPlugin()
    }),

    listeners(() => ({
        submitPluginSuccess: ({ plugin }) => {
            const { source_frontend, id } = plugin
            if (source_frontend && id && pluginsLogic.findMounted()?.values.pluginConfigs[id]?.enabled) {
                frontendAppsLogic.findMounted()?.actions.unloadFrontendApp(id)
                lemonToast.success(`Frontend Source saved! Reloading plugin in 5 seconds...`)
                window.setTimeout(() => {
                    frontendAppsLogic.findMounted()?.actions.loadFrontendApp(id, true)
                }, 5000)
            }
        },
    })),
])
