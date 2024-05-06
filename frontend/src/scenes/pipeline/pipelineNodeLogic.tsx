import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'
import { batchExportFormFields } from 'scenes/batch_exports/batchExportEditLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineNodeTab, PipelineStage, PluginType } from '~/types'

import {
    defaultConfigForPlugin,
    determineInvisibleFields,
    determineRequiredFields,
    getConfigSchemaArray,
    getPluginConfigFormData,
} from './configUtils'
import { pipelineDestinationsLogic } from './destinationsLogic'
import { frontendAppsLogic } from './frontendAppsLogic'
import { importAppsLogic } from './importAppsLogic'
import type { pipelineNodeLogicType } from './pipelineNodeLogicType'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { BatchExportBasedNode, convertToPipelineNode, PipelineBackend, PipelineNode, PluginBasedNode } from './types'

export interface PipelineNodeLogicProps {
    id: number | string
    /** Might be null if a non-existent stage is set in th URL. */
    stage: PipelineStage | null
}

export type PluginUpdatePayload = Pick<PluginBasedNode, 'name' | 'description' | 'enabled' | 'config'>
export type BatchExportUpdatePayload = Pick<
    BatchExportBasedNode,
    'name' | 'description' | 'enabled' | 'service' | 'interval'
>

export const pipelineNodeLogic = kea<pipelineNodeLogicType>([
    props({} as PipelineNodeLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineNodeLogic', id]),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            pipelineDestinationsLogic,
            ['plugins as destinationPlugins'],
            pipelineTransformationsLogic,
            ['plugins as transformationPlugins'],
            frontendAppsLogic,
            ['plugins as frontendAppsPlugins'],
            importAppsLogic,
            ['plugins as importAppsPlugins'],
        ],
    })),
    actions({
        setCurrentTab: (tab: PipelineNodeTab = PipelineNodeTab.Configuration) => ({ tab }),
        loadNode: true,
        updateNode: (payload: PluginUpdatePayload | BatchExportUpdatePayload) => ({
            payload,
        }),
        createNode: (payload: PluginUpdatePayload | BatchExportUpdatePayload) => ({
            payload,
        }),
        setNewConfigurationServiceOrPluginID: (id: number | string | null) => ({ id }),
    }),
    reducers(() => ({
        currentTab: [
            PipelineNodeTab.Configuration as PipelineNodeTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
        newConfigurationServiceOrPluginID: [
            // TODO: this doesn't clear properly if I exit out of the page and more importantly switching to a different stage
            null as null | number | string,
            {
                setNewConfigurationServiceOrPluginID: (_, { id }) => id,
            },
        ],
    })),
    loaders(({ props, values }) => ({
        node: [
            null as PipelineNode | null,
            {
                loadNode: async (_, breakpoint) => {
                    if (!props.stage || props.id === 'new') {
                        return null
                    }
                    let node: PipelineNode | null = null
                    try {
                        if (typeof props.id === 'string') {
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
                createNode: async ({ payload }) => {
                    if (!values.newConfigurationServiceOrPluginID || !values.stage) {
                        return null
                    }
                    if (values.nodeBackend === PipelineBackend.BatchExport) {
                        payload = payload as BatchExportUpdatePayload
                        const batchExport = await api.batchExports.create({
                            paused: !payload.enabled,
                            name: payload.name,
                            interval: payload.interval,
                            destination: payload.service,
                        })
                        return convertToPipelineNode(batchExport, values.stage)
                    } else if (values.maybeNodePlugin) {
                        payload = payload as PluginUpdatePayload
                        const formdata = getPluginConfigFormData(
                            values.maybeNodePlugin.config_schema,
                            defaultConfigForPlugin(values.maybeNodePlugin),
                            { ...payload, enabled: true } // Default enable on creation
                        )
                        formdata.append('plugin', values.maybeNodePlugin.id.toString())
                        formdata.append('order', '99') // TODO: fix this should be at the end of latest here for transformations
                        const pluginConfig = await api.pluginConfigs.create(formdata)
                        return convertToPipelineNode(pluginConfig, values.stage)
                    }
                    return null
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
                    }
                    payload = payload as PluginUpdatePayload
                    const pluginConfig = await api.pluginConfigs.update(
                        props.id as number,
                        getPluginConfigFormData(values.node.plugin.config_schema, values.node.config, payload)
                    )
                    return convertToPipelineNode(pluginConfig, values.node.stage)
                },
            },
        ],
    })),
    forms(({ props, values, asyncActions }) => ({
        configuration: {
            defaults: { name: '', description: '' } as Record<string, any>,
            errors: (form) => {
                if (values.nodeBackend === PipelineBackend.BatchExport) {
                    return batchExportFormFields(props.id === 'new', form as any, { isPipeline: true })
                }
                return Object.fromEntries(
                    values.requiredFields.map((field) => [field, form[field] ? undefined : 'This field is required'])
                )
            },
            submit: async (formValues) => {
                if (values.isNew) {
                    // @ts-expect-error - Sadly Kea logics can't be generic based on props, so TS complains here
                    return await asyncActions.createNode(formValues)
                }
                // @ts-expect-error - Sadly Kea logics can't be generic based on props, so TS complains here
                await asyncActions.updateNode(formValues)
            },
        },
    })),
    selectors(() => ({
        isNew: [(_, p) => [p.id], (id): boolean => id === 'new'],
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
            (s, p) => [s.node, p.id, s.newConfigurationServiceOrPluginID],
            (node, id, newConfigurationServiceOrPluginID): PipelineBackend | null => {
                if (node) {
                    return node.backend
                }
                if (id === 'new') {
                    if (newConfigurationServiceOrPluginID === null) {
                        return null
                    } else if (typeof newConfigurationServiceOrPluginID === 'string') {
                        return PipelineBackend.BatchExport
                    }
                    return PipelineBackend.Plugin
                }
                if (typeof id === 'string') {
                    return PipelineBackend.BatchExport
                }
                return PipelineBackend.Plugin
            },
        ],
        maybeNodePlugin: [
            (s) => [s.node, s.newConfigurationServiceOrPluginID, s.newConfigurationPlugins],
            (node, maybePluginId, plugins): PluginType | null => {
                if (node) {
                    return node.backend === PipelineBackend.Plugin ? node.plugin : null
                }
                if (typeof maybePluginId === 'number') {
                    // in case of new config creations
                    return plugins[maybePluginId] || null
                }
                return null
            },
        ],
        newConfigurationBatchExports: [
            (_, p) => [p.stage],
            (stage): Record<string, string> => {
                if (stage === PipelineStage.Destination) {
                    return {
                        BigQuery: 'BigQuery',
                        Postgres: 'PostgreSQL',
                        Redshift: 'Redshift',
                        S3: 'S3',
                        Snowflake: 'Snowflake',
                    }
                }
                return {}
            },
        ],
        newConfigurationPlugins: [
            (s, p) => [
                p.stage,
                s.destinationPlugins,
                s.transformationPlugins,
                s.frontendAppsPlugins,
                s.importAppsPlugins,
            ],
            (
                stage,
                destinationPlugins,
                transformationPlugins,
                frontendAppsPlugins,
                importAppsPlugins
            ): Record<string, PluginType> => {
                if (stage === PipelineStage.Transformation) {
                    return transformationPlugins
                } else if (stage === PipelineStage.Destination) {
                    return destinationPlugins
                } else if (stage === PipelineStage.SiteApp) {
                    return frontendAppsPlugins
                } else if (stage === PipelineStage.ImportApp) {
                    return importAppsPlugins
                }
                return {}
            },
        ],
        tabs: [
            (_, p) => [p.id],
            (id) => {
                if (id === 'new') {
                    // not used, but just in case
                    return [PipelineNodeTab.Configuration]
                }
                const tabs = Object.values(PipelineNodeTab)
                if (typeof id === 'string') {
                    // Batch export
                    return tabs.filter((t) => t !== PipelineNodeTab.History)
                }
                return tabs
            },
        ],
        savedConfiguration: [
            (s) => [s.node, s.maybeNodePlugin],
            (node, maybeNodePlugin): Record<string, any> | null => {
                if (node) {
                    return node.backend === PipelineBackend.Plugin
                        ? {
                              name: node.name,
                              description: node.description,
                              ...(node.config || defaultConfigForPlugin(node.plugin)),
                          }
                        : { interval: node.interval, destination: node.service.type, ...node.service.config }
                }
                if (maybeNodePlugin) {
                    return defaultConfigForPlugin(maybeNodePlugin)
                }
                return null
            },
        ],
        hiddenFields: [
            (s) => [s.maybeNodePlugin, s.configuration],
            (maybeNodePlugin, configuration): string[] => {
                if (maybeNodePlugin) {
                    return determineInvisibleFields((fieldName) => configuration[fieldName], maybeNodePlugin)
                }
                return []
            },
        ],
        requiredFields: [
            (s) => [s.maybeNodePlugin, s.configuration],
            (maybeNodePlugin, configuration): string[] => {
                if (maybeNodePlugin) {
                    return determineRequiredFields((fieldName) => configuration[fieldName], maybeNodePlugin)
                }
                return []
            },
        ],
        isConfigurable: [
            (s) => [s.maybeNodePlugin],
            (maybeNodePlugin): boolean =>
                !maybeNodePlugin || getConfigSchemaArray(maybeNodePlugin.config_schema).length > 0,
        ],
        id: [(_, p) => [p.id], (id) => id],
        stage: [(_, p) => [p.stage], (stage) => stage],
    })),
    listeners(({ actions, values }) => ({
        loadNodeSuccess: () => {
            actions.resetConfiguration(values.savedConfiguration || {})
            // TODO: Update entry in the relevant list logic
        },
        setNewSelected: () => {
            actions.resetConfiguration({}) // If the user switches to a different plugin/batch export, then clear the form
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
    afterMount(({ values, actions }) => {
        if (!values.isNew) {
            actions.loadNode()
        }
    }),
])
