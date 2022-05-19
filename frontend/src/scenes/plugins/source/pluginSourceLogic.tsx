import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { pluginSourceLogicType } from './pluginSourceLogicType'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { lemonToast } from 'lib/components/lemonToast'
import { validateJson } from 'lib/utils'
import React from 'react'
import { FormErrors } from 'lib/forms/Errors'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

interface PluginSourceProps {
    id: number
    onClose?: () => void
}

export const pluginSourceLogic = kea<pluginSourceLogicType<PluginSourceProps>>([
    path(['scenes', 'plugins', 'edit', 'pluginSourceLogic']),
    props({} as PluginSourceProps),
    key((props) => props.id),

    actions({
        setCurrentFile: (currentFile: string) => ({ currentFile }),
        closePluginSource: true,
    }),

    reducers({
        currentFile: ['plugin.json', { setCurrentFile: (_, { currentFile }) => currentFile }],
    }),

    forms(({ actions, props, values }) => ({
        pluginSource: {
            defaults: {},
            errors: (values) => ({
                'plugin.json': !validateJson(values['plugin.json']) ? 'Not valid JSON' : '',
            }),
            submit: async () => {
                const { pluginSource } = values
                const response = await api.update(
                    `api/organizations/@current/plugins/${props.id}/update_source`,
                    pluginSource
                )
                actions.resetPluginSource(response)
                pluginsLogic.findMounted()?.actions.loadPlugins()
            },
        },
    })),

    loaders(({ props }) => ({
        pluginSource: {
            fetchPluginSource: async () => {
                const response = await api.get(`api/organizations/@current/plugins/${props.id}/source`)
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
        fileNames: [() => [], (): string[] => ['plugin.json', 'index.ts']],
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
