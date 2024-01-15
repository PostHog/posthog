import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { actionToUrl, urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineAppKind, PipelineAppTab, PluginConfigTypeNew, PluginType } from '~/types'

import { PipelineAppBackend, pipelineDestinationsLogic } from './destinationsLogic'
import type { pipelineAppLogicType } from './pipelineAppLogicType'

export interface PipelineAppLogicProps {
    id: number | string
    /** Might be null if a non-existent kind is set in th URL. */
    kind: PipelineAppKind | null
}

export const pipelineAppLogic = kea<pipelineAppLogicType>([
    props({} as PipelineAppLogicProps),
    key(({ kind, id }) => `${kind}:${id}`),
    path((id) => ['scenes', 'pipeline', 'pipelineAppLogic', id]),
    connect(() => ({
        values: [pipelineDestinationsLogic, ['plugins', 'pluginsLoading', 'pluginConfigs', 'pluginConfigsLoading']],
    })),
    actions({
        setCurrentTab: (tab: PipelineAppTab = PipelineAppTab.Configuration) => ({ tab }),
    }),
    reducers({
        currentTab: [
            PipelineAppTab.Configuration as PipelineAppTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors(() => ({
        breadcrumbs: [
            (s, p) => [p.id, p.kind, s.maybePluginConfig],
            (id, kind, maybePluginConfig): Breadcrumb[] => [
                {
                    key: Scene.Pipeline,
                    name: 'Data pipeline',
                    path: urls.pipeline(),
                },
                {
                    key: kind || 'unknown',
                    name: kind ? capitalizeFirstLetter(kind) : 'Unknown',
                    path: urls.pipeline(),
                },
                {
                    key: [Scene.PipelineApp, id],
                    name: maybePluginConfig ? maybePluginConfig.name || 'Unnamed' : 'Unknown',
                },
            ],
        ],
        appBackend: [
            (_, p) => [p.id],
            (id): PipelineAppBackend =>
                typeof id === 'string' ? PipelineAppBackend.BatchExport : PipelineAppBackend.Plugin,
        ],
        loading: [
            (s) => [s.appBackend, s.pluginConfigsLoading, s.pluginsLoading],
            (appBackend, pluginConfigsLoading, pluginsLoading): boolean => {
                if (appBackend === PipelineAppBackend.BatchExport) {
                    return false // TODO: Support loading state for batch exports
                }
                return pluginConfigsLoading || pluginsLoading
            },
        ],
        tabs: [
            (s) => [s.appType],
            (appType) => {
                if (appType === DestinationTypeKind.BatchExport) {
                    return Object.values(PipelineAppTabs).filter((t) => t !== PipelineAppTabs.History)
                }

                return Object.values(PipelineAppTabs)
            },
        ],
        maybePluginConfig: [
            (s, p) => [s.pluginConfigs, s.appBackend, p.id],
            (pluginConfigs, appBackend, maybePluginConfigId): PluginConfigTypeNew | null => {
                if (appBackend !== 'plugin') {
                    return null
                }
                return pluginConfigs[maybePluginConfigId] || null
            },
        ],
        maybePlugin: [
            (s) => [s.plugins, s.maybePluginConfig],
            (plugins, maybePluginConfig): PluginType | null => {
                if (!maybePluginConfig) {
                    return null
                }
                return plugins[maybePluginConfig.plugin] || null
            },
        ],
        kind: [(_, p) => [p.kind], (kind) => kind],
    })),
    forms({
        configuration: {
            // TOOD: Validate that required fields are filled in
            submit: () => {
                // TODO
            },
        },
    }),
    actionToUrl(({ values, props }) => {
        return {
            setCurrentTab: () => [urls.pipelineApp(props.kind as PipelineAppKind, props.id, values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/pipeline/:kindTab/:id/:appTab': ({ appTab }) => {
            if (appTab !== values.currentTab && Object.values(PipelineAppTab).includes(appTab as PipelineAppTab)) {
                actions.setCurrentTab(appTab as PipelineAppTab)
            }
        },
    })),
])
