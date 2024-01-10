import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { actionToUrl, urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineAppTabs, PipelineTabs, PluginConfigTypeNew, PluginType } from '~/types'

import { DestinationType, pipelineDestinationsLogic } from './destinationsLogic'
import type { pipelineAppLogicType } from './pipelineAppLogicType'

export interface PipelineAppLogicProps {
    id: number
    kind: PipelineTabs
}

export const pipelineAppLogic = kea<pipelineAppLogicType>([
    props({} as PipelineAppLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineAppLogic', id]),
    connect(() => ({
        values: [pipelineDestinationsLogic, ['plugins', 'pluginConfigs']],
    })),
    actions({
        setCurrentTab: (tab: PipelineAppTabs = PipelineAppTabs.Configuration) => ({ tab }),
        setKind: (kind: PipelineTabs) => ({ kind }),
    }),
    reducers({
        currentTab: [
            PipelineAppTabs.Configuration as PipelineAppTabs,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s, p) => [p.kind, s.maybePluginConfig],
            (kind, maybePluginConfig): Breadcrumb[] => [
                {
                    key: Scene.Pipeline,
                    name: 'Data pipeline',
                    path: urls.pipeline(),
                },
                {
                    key: 'Kind',
                    name: capitalizeFirstLetter(kind),
                },
                {
                    key: 'todo',
                    name: maybePluginConfig?.name || 'Unknown',
                },
            ],
        ],
        appType: [
            (_, p) => [p.id],
            (id): DestinationType['type'] => (typeof id === 'number' ? 'webhook' : 'batch_export'),
        ],
        maybePluginConfig: [
            (s, p) => [s.pluginConfigs, s.appType, p.id],
            (pluginConfigs, appType, maybePluginConfigId): PluginConfigTypeNew | null => {
                if (appType !== 'webhook') {
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
    }),
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
            setCurrentTab: () => [urls.pipelineApp(props.kind, props.id, values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/pipeline/:kind/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab && Object.values(PipelineAppTabs).includes(tab as PipelineAppTabs)) {
                actions.setCurrentTab(tab as PipelineAppTabs)
            }
        },
    })),
])
