import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import api from 'lib/api'
import { FormErrors } from 'lib/forms/Errors'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { validateJson } from 'lib/utils'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { formatSource } from 'scenes/pipeline/appCodeLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

import type { pluginSourceLogicType } from './pluginSourceLogicType'

export interface PluginSourceProps {
    pluginId: number
    pluginConfigId?: number
    onClose?: () => void
}

const LEAVE_WARNING = 'You have unsaved changes in your plugin. Are you sure you want to exit?'

export const pluginSourceLogic = kea<pluginSourceLogicType>([
    path(['scenes', 'plugins', 'edit', 'pluginSourceLogic']),
    props({} as PluginSourceProps),
    key((props) => props.pluginConfigId ?? `plugin-${props.pluginId}`),

    connect({ logic: [pluginsLogic] }),

    actions({
        setCurrentFile: (currentFile: string) => ({ currentFile }),
        closePluginSource: true,
        resetAndClose: true,
    }),

    reducers({
        currentFile: [
            'plugin.json',
            {
                setCurrentFile: (_, { currentFile }) => currentFile,
            },
        ],
    }),

    forms(({ actions, props, values }) => ({
        pluginSource: {
            defaults: {} as Record<string, string>,
            errors: (values) => ({
                'plugin.json': !validateJson(values['plugin.json']) ? 'Not valid JSON' : '',
            }),
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
                actions.resetPluginSource(response)
                pluginsLogic.findMounted()?.actions.loadPlugins()

                const appsLogic = frontendAppsLogic.findMounted()
                if (appsLogic && props.pluginConfigId) {
                    const appConfig = appsLogic.values.appConfigs[props.pluginConfigId]
                    if (appConfig) {
                        appsLogic.actions.unloadFrontendApp(appConfig.pluginConfigId)
                        if (
                            !pluginsLogic.findMounted() ||
                            pluginsLogic.values.getPluginConfig(props.pluginConfigId)?.enabled
                        ) {
                            appsLogic.actions.loadFrontendApp(appConfig.pluginConfigId, appConfig.pluginId, true)
                        }
                    }
                }
            },
        },
    })),

    loaders(({ props }) => ({
        pluginSource: {
            fetchPluginSource: async () => {
                const response = await api.get(`api/organizations/@current/plugins/${props.pluginId}/source`)
                return response ?? {}
            },
        },
    })),

    selectors({
        name: [
            (s) => [s.pluginSource],
            (pluginSource) => {
                try {
                    return JSON.parse(pluginSource['plugin.json']).name
                } catch (e) {
                    return undefined
                }
            },
        ],
        fileNames: [
            () => [],
            (): string[] => {
                return Array.from(new Set(['plugin.json', 'index.ts', 'frontend.tsx', 'site.ts']))
            },
        ],
    }),
    beforeUnload(({ values }) => ({
        enabled: () => values.pluginSourceChanged,
        message: LEAVE_WARNING,
    })),
    listeners(({ actions, props, values }) => ({
        resetAndClose: () => {
            actions.resetPluginSource()
            props.onClose?.()
        },
        closePluginSource: () => {
            if (values.pluginSourceChanged) {
                if (confirm(LEAVE_WARNING)) {
                    actions.resetAndClose()
                }
            } else {
                actions.resetAndClose()
            }
        },
        submitPluginSourceSuccess: () => {
            lemonToast.success('App saved!', {
                button: {
                    label: 'Close drawer',
                    action: actions.closePluginSource,
                },
                position: 'top-right',
                toastId: `submit-plugin-${props.pluginConfigId}`,
            })
        },
        submitPluginSourceFailure: ({ error }) => {
            lemonToast.error(
                <>
                    <div>Please fix the following errors:</div>
                    <pre>{String(error?.message || error)}</pre>
                    <FormErrors errors={values.pluginSourceErrors} />
                </>,
                { position: 'top-right' }
            )
        },
        [pluginsLogic.actionTypes.setEditingSource]: () => {
            // reset if re-opening drawer and pluginSourceLogic remained mounted
            if (pluginsLogic.values.editingPluginId === props.pluginId) {
                actions.resetPluginSource()
                actions.fetchPluginSource()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.resetPluginSource()
        actions.fetchPluginSource()
    }),
])
