import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'

import type { appsCodeLogicType } from './appCodeLogicType'

export interface AppCodeProps {
    pluginId: number
}

export const appsCodeLogic = kea<appsCodeLogicType>([
    props({} as AppCodeProps),
    key(({ pluginId }: AppCodeProps) => pluginId),
    path((id) => ['scenes', 'pipeline', 'appsCodeLogic', id]),
    actions({
        setCurrentFile: (currentFile: string) => ({ currentFile }),
        editAppCode: true,
        cancelEditing: true,
        fetchPluginSource: true,
        fetchPluginSourceComplete: true,
        setFilenames: (code: Record<string, string>) => ({ code }),
    }),
    reducers({
        currentFile: [
            'plugin.json',
            {
                setCurrentFile: (_, { currentFile }) => currentFile,
            },
        ],
        editingAppCode: [
            false,
            {
                editAppCode: () => true,
                cancelEditing: () => false,
                submitPluginSourceSuccess: () => false,
            },
        ],
        pluginSourceLoading: [
            false,
            {
                fetchPluginSource: () => true,
                fetchPluginSourceComplete: () => false,
            },
        ],
        filenames: [
            [] as string[],
            {
                setFilenames: (_, { code }) => (code ? Object.keys(code) : []),
            },
        ],
    }),
    listeners(({ actions, props }) => ({
        cancelEditing: async () => {
            actions.fetchPluginSource()
        },
        fetchPluginSource: async () => {
            try {
                const response = await api.get(`api/organizations/@current/plugins/${props.pluginId}/source`)
                const formattedCode = {}
                for (const [file, source] of Object.entries(response || {})) {
                    if (source && file.match(/\.(ts|tsx|js|jsx|json)$/)) {
                        try {
                            const prettySource = await formatSource(file, source as string)
                            formattedCode[file] = prettySource
                        } catch {
                            formattedCode[file] = source
                        }
                    }
                }
                actions.setPluginSourceValues(formattedCode)
                actions.setFilenames(formattedCode)
            } finally {
                actions.fetchPluginSourceComplete()
            }
        },
    })),
    forms(({ actions, props, values }) => ({
        pluginSource: {
            defaults: {} as Record<string, string>,
            preSubmit: async () => {
                const changes = {}
                const errors = {}
                for (const [file, source] of Object.entries(values.pluginSource)) {
                    if (source && file.match(/\.(ts|tsx|js|jsx|json)$/)) {
                        try {
                            const prettySource = await formatSource(file, source)
                            if (prettySource !== source) {
                                changes[file] = prettySource
                            }
                        } catch (e: any) {
                            errors[file] = e.message
                        }
                    }
                }
                if (Object.keys(changes).length > 0) {
                    actions.setPluginSourceValues(changes)
                }
                actions.setPluginSourceManualErrors(errors)
            },
            submit: async () => {
                const response = await api.update(
                    `api/organizations/@current/plugins/${props.pluginId}/update_source`,
                    values.pluginSource
                )
                actions.setPluginSourceValues(response)
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.fetchPluginSource()
    }),
])

export async function formatSource(filename: string, source: string): Promise<string> {
    if (filename.endsWith('.json')) {
        return JSON.stringify(JSON.parse(source), null, 4) + '\n'
    }

    // Lazy-load prettier, as it's pretty big and its only use is formatting app source code
    const prettier = (await import('prettier/standalone')).default
    const parserTypeScript = (await import('prettier/parser-typescript')).default

    return prettier.format(source, {
        filepath: filename,
        parser: 'typescript',
        plugins: [parserTypeScript as any],
        // copied from .prettierrc
        semi: false,
        trailingComma: 'es5',
        singleQuote: true,
        tabWidth: 4,
        printWidth: 120,
    })
}
