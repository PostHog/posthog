import { actions, afterMount, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'

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
    'index.ts': string
    'frontend.tsx': string
    'config.json': string
}

interface EditorSourceFile {
    name: string
    language: string
    value: string
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
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const pluginSourceLogic = kea<pluginSourceLogicType<EditorSourceFile, PluginSourceProps, PluginSourceSlice>>([
    path(['scenes', 'plugins', 'edit', 'pluginSourceLogic']),
    props({} as PluginSourceProps),
    key((props) => props.id),
    connect({ values: [featureFlagLogic, ['featureFlags']] }),

    actions({
        setFile: (file: string) => ({ file }),
        setActiveFileValue: (value: string) => ({ value }),
    }),

    defaults({
        plugin: {
            name: '',
            'index.ts': defaultSource,
            'frontend.tsx': '',
            'config.json': JSON.stringify(defaultConfig, null, 2),
        } as PluginSourceSlice,
    }),

    forms(({ props, values }) => ({
        plugin: {
            errors: ({ name, config_schema }) => ({
                name: !name ? 'Please enter a name' : '',
                'config.json': !validateJson(config_schema) ? 'Not valid JSON' : '',
            }),
            submit: async () => {
                const { plugin } = values
                const response = await api.update(`api/organizations/@current/plugins/${props.id}`, {
                    name: plugin.name,
                    source: plugin['index.ts'],
                    source_frontend: plugin['frontend.tsx'],
                    config_schema: JSON.parse(plugin['config.json']),
                })
                return {
                    name: response.name,
                    'index.ts': response.source,
                    'frontend.tsx': response.source_frontend,
                    'config.json': JSON.stringify(response.config_schema, null, 2),
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
                    'index.ts': response.source,
                    'frontend.tsx': response.source_frontend,
                    'config.json': JSON.stringify(response.config_schema, null, 2),
                }
            },
        },
    })),

    reducers({
        file: ['index.ts', { setFile: (_, { file }) => file }],
    }),

    selectors({
        files: [
            (s) => [s.plugin, s.featureFlags],
            (plugin, featureFlags): Record<string, EditorSourceFile> => {
                const files: Record<string, EditorSourceFile> = {}

                files['index.ts'] = {
                    name: 'index.ts',
                    language: 'typescript',
                    value: plugin['index.ts'],
                }
                if (featureFlags[FEATURE_FLAGS.FRONTEND_APPS]) {
                    files['frontend.tsx'] = {
                        name: 'frontend.tsx',
                        language: 'typescript',
                        value: plugin['frontend.tsx'],
                    }
                }
                files['config.json'] = {
                    name: 'config.json',
                    language: 'json',
                    value: plugin['config.json'],
                }

                return files
            },
        ],
        activeFile: [(s) => [s.files, s.file], (files, file): EditorSourceFile => files[file]],
    }),

    afterMount(({ actions }) => {
        actions.getPlugin()
    }),

    listeners(({ actions, values }) => ({
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
        setActiveFileValue: ({ value }) => {
            const { activeFile } = values
            if (activeFile?.name === 'index.ts') {
                actions.setPluginValue('source', value)
            } else if (activeFile?.name === 'frontend.tsx') {
                actions.setPluginValue('source_frontend', value)
            } else if (activeFile?.name === 'config_json') {
                actions.setPluginValue('config.json', value)
            }
        },
    })),
])
