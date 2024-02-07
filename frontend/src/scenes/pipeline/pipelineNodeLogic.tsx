import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'
import { batchExportFormFields } from 'scenes/batch_exports/batchExportEditLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineNodeTab, PipelineStage } from '~/types'

import {
    defaultConfigForPlugin,
    determineInvisibleFields,
    determineRequiredFields,
    getConfigSchemaArray,
    getPluginConfigFormData,
} from './configUtils'
import type { pipelineNodeLogicType } from './pipelineNodeLogicType'
import {
    BatchExportBasedStep,
    convertToPipelineNode,
    PipelineBackend,
    PipelineNode,
    PluginBasedStepBase,
} from './types'

export interface PipelineNodeLogicProps {
    id: number | string
    /** Might be null if a non-existent stage is set in th URL. */
    stage: PipelineStage | null
}

export type PluginUpdatePayload = Pick<PluginBasedStepBase, 'name' | 'description' | 'enabled' | 'config'>
export type BatchExportUpdatePayload = Pick<
    BatchExportBasedStep,
    'name' | 'description' | 'enabled' | 'service' | 'interval'
>

export const pipelineNodeLogic = kea<pipelineNodeLogicType>([
    props({} as PipelineNodeLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineNodeLogic', id]),
    actions({
        setCurrentTab: (tab: PipelineNodeTab = PipelineNodeTab.Configuration) => ({ tab }),
        loadNode: true,
        updateNode: (payload: PluginUpdatePayload | BatchExportUpdatePayload) => ({
            payload,
        }),
    }),
    reducers({
        currentTab: [
            PipelineNodeTab.Configuration as PipelineNodeTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        node: [
            null as PipelineNode | null,
            {
                loadNode: async (_, breakpoint) => {
                    if (!props.stage) {
                        return null
                    }
                    let node: PipelineNode | null = null
                    try {
                        if (typeof props.id === 'string') {
                            if (props.stage !== PipelineStage.Destination) {
                                return null
                            }
                            const batchExport = await api.batchExports.get(props.id)
                            node = convertToPipelineNode(batchExport, props.stage)
                        } else {
                            const pluginConfig = await api.pluginConfigs.get(props.id)
                            node = convertToPipelineNode(pluginConfig, props.stage)
                        }
                    } catch (e: any) {
                        if (e.status === 404) {
                            return null
                        }
                    }
                    breakpoint()
                    return node
                },
                updateNode: async ({ payload }) => {
                    if (!values.node) {
                        return null
                    }
                    if (values.node.backend === PipelineBackend.BatchExport) {
                        payload = payload as BatchExportUpdatePayload
                        const batchExport = await api.batchExports.update(props.id as string, {
                            paused: !payload.enabled,
                            name: payload.name,
                            interval: payload.interval,
                            destination: payload.service,
                        })
                        return convertToPipelineNode(batchExport, values.node.stage)
                    } else {
                        payload = payload as PluginUpdatePayload
                        const pluginConfig = await api.pluginConfigs.update(
                            props.id as number,
                            getPluginConfigFormData(values.node.plugin.config_schema, values.node.config, payload)
                        )
                        return convertToPipelineNode(pluginConfig, values.node.stage)
                    }
                },
            },
        ],
    })),
    forms(({ props, values, asyncActions }) => ({
        configuration: {
            defaults: {} as Record<string, any>,
            errors: (form) => {
                if (values.nodeBackend === PipelineBackend.BatchExport) {
                    return batchExportFormFields(props.id === 'new', form as any, { isPipeline: true })
                } else {
                    return Object.fromEntries(
                        values.requiredFields.map((field) => [
                            field,
                            form[field] ? undefined : 'This field is required',
                        ])
                    )
                }
            },
            submit: async (formValues) => {
                // @ts-expect-error - Sadly Kea logics can't be generic based on props, so TS complains here
                await asyncActions.updateNode(formValues)
            },
        },
    })),
    selectors(() => ({
        breadcrumbs: [
            (s, p) => [p.id, p.stage, s.node, s.nodeLoading],
            (id, stage, node, nodeLoading): Breadcrumb[] => [
                {
                    key: Scene.Pipeline,
                    name: 'Data pipeline',
                    path: urls.pipeline(),
                },
                {
                    key: stage || 'unknown',
                    name: stage ? capitalizeFirstLetter(stage) : 'Unknown',
                    path: urls.pipeline(),
                },
                {
                    key: [Scene.PipelineNode, id],
                    name: node ? node.name || 'Unnamed' : nodeLoading ? null : 'Not found',
                },
            ],
        ],
        nodeBackend: [
            (_, p) => [p.id],
            (id): PipelineBackend => (typeof id === 'string' ? PipelineBackend.BatchExport : PipelineBackend.Plugin),
        ],
        tabs: [
            (_, p) => [p.id],
            (id) => {
                const tabs = Object.values(PipelineNodeTab)
                if (typeof id === 'string') {
                    // Batch export
                    return tabs.filter((t) => t !== PipelineNodeTab.History)
                }
                return tabs
            },
        ],
        savedConfiguration: [
            (s) => [s.node],
            (node): Record<string, any> | null =>
                node
                    ? node.backend === PipelineBackend.Plugin
                        ? node.config || defaultConfigForPlugin(node.plugin)
                        : { interval: node.interval, destination: node.service.type, ...node.service.config }
                    : null,
        ],
        hiddenFields: [
            (s) => [s.node, s.configuration],
            (node, configuration): string[] => {
                if (node?.backend === PipelineBackend.Plugin) {
                    return determineInvisibleFields((fieldName) => configuration[fieldName], node.plugin)
                }
                return []
            },
        ],
        requiredFields: [
            (s) => [s.node, s.configuration],
            (node, configuration): string[] => {
                if (node?.backend === PipelineBackend.Plugin) {
                    return determineRequiredFields((fieldName) => configuration[fieldName], node.plugin)
                }
                return []
            },
        ],
        isConfigurable: [
            (s) => [s.node],
            (node): boolean =>
                node?.backend === PipelineBackend.Plugin && getConfigSchemaArray(node.plugin.config_schema).length > 0,
        ],
        id: [(_, p) => [p.id], (id) => id],
        stage: [(_, p) => [p.stage], (stage) => stage],
    })),
    listeners(({ actions, values }) => ({
        loadNodeSuccess: () => {
            actions.resetConfiguration(values.savedConfiguration || {})
            // TODO: Update entry in the relevant list logic
        },
        setConfigurationValue: async ({ name, value }) => {
            if (name[0] === 'json_config_file' && value) {
                try {
                    const loadedFile: string = await new Promise((resolve, reject) => {
                        const filereader = new FileReader()
                        filereader.onload = (e) => resolve(e.target?.result as string)
                        filereader.onerror = (e) => reject(e)
                        filereader.readAsText(value[0])
                    })
                    const jsonConfig = JSON.parse(loadedFile)
                    actions.setConfigurationValues({
                        ...values.configuration,
                        project_id: jsonConfig.project_id,
                        private_key: jsonConfig.private_key,
                        private_key_id: jsonConfig.private_key_id,
                        client_email: jsonConfig.client_email,
                        token_uri: jsonConfig.token_uri,
                    })
                } catch (e) {
                    actions.setConfigurationManualErrors({
                        json_config_file: 'The config file is not valid',
                    })
                }
            }
        },
    })),
    actionToUrl(({ values, props }) => {
        return {
            setCurrentTab: () => [urls.pipelineNode(props.stage as PipelineStage, props.id, values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/pipeline/:stage/:id/:nodeTab': ({ nodeTab }) => {
            if (nodeTab !== values.currentTab && Object.values(PipelineNodeTab).includes(nodeTab as PipelineNodeTab)) {
                actions.setCurrentTab(nodeTab as PipelineNodeTab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNode()
    }),
])
