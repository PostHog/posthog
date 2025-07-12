import { actions, kea, key, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { BatchExportBackfills } from 'scenes/data-pipelines/batch-exports/BatchExportBackfills'
import { BatchExportRuns } from 'scenes/data-pipelines/batch-exports/BatchExportRuns'
import { PipelineNodeLogs } from 'scenes/pipeline/PipelineNodeLogs'
import { PipelineNodeMetrics } from 'scenes/pipeline/PipelineNodeMetrics'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BatchExportService, Breadcrumb, PipelineStage } from '~/types'

import { BatchExportConfiguration } from './BatchExportConfiguration'
import { BatchExportConfigurationLogicProps } from './batchExportConfigurationLogic'
import type { batchExportSceneLogicType } from './BatchExportSceneType'

const BATCH_EXPORT_SCENE_TABS = ['configuration', 'metrics', 'logs', 'runs', 'backfills'] as const
export type BatchExportSceneTab = (typeof BATCH_EXPORT_SCENE_TABS)[number]

export const batchExportSceneLogic = kea<batchExportSceneLogicType>([
    props({} as BatchExportConfigurationLogicProps),
    key(({ id }: BatchExportConfigurationLogicProps) => id ?? 'new'),
    path((key) => ['scenes', 'data-pipelines', 'batch-exports', 'batchExportSceneLogic', key]),
    actions({
        setCurrentTab: (tab: BatchExportSceneTab) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            'configuration' as BatchExportSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.DataPipelines,
                        name: 'Data pipelines',
                        path: urls.dataPipelines(),
                    },
                    {
                        key: [Scene.DataPipelines, 'destinations'],
                        name: 'Destinations',
                        path: urls.dataPipelines('destinations'),
                    },

                    {
                        key: Scene.BatchExport,
                        name: 'Batch export',
                    },
                ]
            },
        ],
    }),
    actionToUrl(({ values }) => ({
        setCurrentTab: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    tab: values.currentTab,
                },
                router.values.hashParams,
            ]
        },
    })),
    urlToAction(({ actions, values }) => {
        const reactToTabChange = (_: any, search: Record<string, string>): void => {
            const possibleTab = (search.tab ?? 'configuration') as BatchExportSceneTab

            const tab = BATCH_EXPORT_SCENE_TABS.includes(possibleTab) ? possibleTab : 'configuration'
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab)
            }
        }

        return {
            // All possible routes for this scene need to be listed here
            [urls.batchExport(':id')]: reactToTabChange,
        }
    }),
])

export const scene: SceneExport = {
    component: BatchExportScene,
    logic: batchExportSceneLogic,
    paramsToProps: ({ params: { id, service } }): (typeof batchExportSceneLogic)['props'] => ({
        id: id === 'new' ? null : id,
        service: service as BatchExportService['type'] | null,
    }),
}

export function BatchExportScene(): JSX.Element {
    const { currentTab, logicProps } = useValues(batchExportSceneLogic)
    const { setCurrentTab } = useActions(batchExportSceneLogic)

    const { id, service } = logicProps

    const tabs: (LemonTab<BatchExportSceneTab> | null)[] = [
        {
            label: 'Configuration',
            key: 'configuration',
            content: <BatchExportConfiguration id={id} service={service} />,
        },
        id
            ? {
                  label: 'Metrics',
                  key: 'metrics',
                  content: <PipelineNodeMetrics id={id} />,
              }
            : null,
        id
            ? {
                  label: 'Logs',
                  key: 'logs',
                  content: <PipelineNodeLogs id={id} stage={PipelineStage.Destination} />,
              }
            : null,
        id
            ? {
                  label: 'Runs',
                  key: 'runs',
                  content: <BatchExportRuns id={id} />,
              }
            : null,
        id
            ? {
                  label: 'Backfills',
                  key: 'backfills',
                  content: <BatchExportBackfills id={id} />,
              }
            : null,
    ]

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} />
}
