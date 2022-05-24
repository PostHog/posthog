import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { pluginSourceLogicType } from './pluginSourceLogicType'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { lemonToast } from 'lib/components/lemonToast'
import { validateJson } from 'lib/utils'
import React from 'react'
import { FormErrors } from 'lib/forms/Errors'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { formatSource } from 'scenes/plugins/source/formatSource'

export interface PluginSourceProps {
    pluginId: number
    pluginConfigId?: number
    onClose?: () => void
}

export const pluginSourceLogic = kea<pluginSourceLogicType>([
    path(['scenes', 'plugins', 'edit', 'pluginSourceLogic']),
    props({} as PluginSourceProps),
    key((props) => props.pluginConfigId ?? `plugin-${props.pluginId}`),

    connect({ values: [featureFlagLogic, ['featureFlags']] }),

    actions({
        setCurrentFile: (currentFile: string) => ({ currentFile }),
        closePluginSource: true,
    }),

    reducers({
        currentFile: ['plugin.json', { setCurrentFile: (_, { currentFile }) => currentFile }],
    }),

    forms(({ actions, props, values }) => ({
        pluginSource: {
            defaults: {} as Record<string, string>,
            errors: (values) => ({
                'plugin.json': !validateJson(values['plugin.json']) ? 'Not valid JSON' : '',
            }),
            preSubmit: () => {
                const changes = {}
                const errors = {}
                for (const [file, source] of Object.entries(values.pluginSource)) {
                    if (source && file.match(/\.(ts|tsx|js|jsx|json)$/)) {
                        try {
                            const prettySource = formatSource(file, source)
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
            (s) => [s.featureFlags],
            (featureFlags): string[] =>
                featureFlags[FEATURE_FLAGS.FRONTEND_APPS]
                    ? ['plugin.json', 'index.ts', 'frontend.tsx']
                    : ['plugin.json', 'index.ts'],
        ],
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
    })),

    afterMount(({ actions }) => {
        actions.fetchPluginSource()
    }),
])
