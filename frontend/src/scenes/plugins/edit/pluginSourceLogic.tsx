import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { pluginSourceLogicType } from './pluginSourceLogicType'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { lemonToast } from 'lib/components/lemonToast'
import { validateJson } from 'lib/utils'
import React from 'react'
import { FormErrors } from 'lib/forms/Errors'

interface PluginSourceProps {
    id: number
    onClose?: () => void
}

interface PluginSource {
    name: string
    'index.ts': string
    'config.json': string
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
export async function runEveryHour(meta) {
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

export const pluginSourceLogic = kea<pluginSourceLogicType<PluginSource, PluginSourceProps>>([
    path(['scenes', 'plugins', 'edit', 'pluginSourceLogic']),
    props({} as PluginSourceProps),
    key((props) => props.id),

    actions({
        setCurrentFile: (currentFile: string) => ({ currentFile }),
        closePluginSource: true,
    }),

    reducers({
        currentFile: ['index.ts', { setCurrentFile: (_, { currentFile }) => currentFile }],
    }),

    forms(({ actions, props, values }) => ({
        pluginSource: {
            defaults: {
                name: '',
                'index.ts': defaultSource,
                'config.json': JSON.stringify(defaultConfig, null, 2),
            } as PluginSource,
            errors: (values) => ({
                name: !values.name ? 'Please enter a name' : '',
                'config.json': !validateJson(values['config.json']) ? 'Not valid JSON' : '',
            }),
            submit: async () => {
                const { pluginSource } = values
                const response = await api.update(`api/organizations/@current/plugins/${props.id}`, {
                    name: pluginSource.name,
                    source: pluginSource['index.ts'],
                    config_schema: JSON.parse(pluginSource['config.json']),
                })
                actions.resetPluginSource({
                    name: response.name,
                    'index.ts': response.source,
                    'config.json': JSON.stringify(response.config_schema, null, 2),
                })
            },
        },
    })),

    loaders(({ props }) => ({
        pluginSource: {
            fetchPluginSource: async () => {
                const response = await api.get(`api/organizations/@current/plugins/${props.id}`)
                return {
                    name: response.name,
                    'index.ts': response.source,
                    'config.json': JSON.stringify(response.config_schema, null, 2),
                }
            },
        },
    })),

    selectors({
        name: [(s) => [s.pluginSource], (pluginSource) => pluginSource.name],
        fileNames: [() => [], (): string[] => ['index.ts', 'config.json']],
    }),

    listeners(({ props, values }) => ({
        closePluginSource: () => {
            const close = (): void => props.onClose?.()
            if (values.pluginSourceChanged) {
                if (confirm('You have unsaved changes in your plugin. Are you sure you want to exit?')) {
                    close()
                }
            } else {
                close()
            }
        },
        submitPluginSourceSuccess: () => {
            lemonToast.success('App saved!', {
                button: {
                    label: 'Close drawer',
                    action: () => props.onClose?.(),
                },
                toastId: `submit-plugin-${props.id}`,
            })
        },
        submitPluginSourceFailure: () => {
            lemonToast.error(
                <>
                    <div>Please fix the following errors:</div>
                    <FormErrors errors={values.pluginSourceErrors} />
                </>
            )
        },
    })),

    afterMount(({ actions }) => {
        actions.fetchPluginSource()
    }),
])
