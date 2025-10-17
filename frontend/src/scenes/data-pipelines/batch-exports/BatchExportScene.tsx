import { actions, kea, key, path, props, reducers, selectors, useActions, useMountedLogic, useValues } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { BatchExportBackfills } from 'scenes/data-pipelines/batch-exports/BatchExportBackfills'
import { BatchExportRuns } from 'scenes/data-pipelines/batch-exports/BatchExportRuns'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { HogFunctionSkeleton } from 'scenes/hog-functions/misc/HogFunctionSkeleton'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { BATCH_EXPORT_SERVICE_NAMES, BatchExportService, Breadcrumb } from '~/types'

import { PipelineNodeLogs } from '../legacy-plugins/PipelineNodeLogs'
import { BatchExportConfiguration } from './BatchExportConfiguration'
import {
    BatchExportConfigurationClearChangesButton,
    BatchExportConfigurationSaveButton,
} from './BatchExportConfigurationButtons'
import { RenderBatchExportIcon } from './BatchExportIcon'
import type { batchExportSceneLogicType } from './BatchExportSceneType'
import { BatchExportsMetrics } from './BatchExportsMetrics'
import { BatchExportConfigurationLogicProps, batchExportConfigurationLogic } from './batchExportConfigurationLogic'
import { normalizeBatchExportService } from './utils'

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
                        iconType: 'data_pipeline',
                    },
                    {
                        key: [Scene.DataPipelines, 'destinations'],
                        name: 'Destinations',
                        path: urls.dataPipelines('destinations'),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: Scene.BatchExport,
                        name: 'Batch export',
                        iconType: 'data_pipeline',
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
            [urls.batchExportNew(':service')]: reactToTabChange,
        }
    }),
])

export const scene: SceneExport = {
    component: BatchExportScene,
    logic: batchExportSceneLogic,
    paramsToProps: ({ params: { id, service } }): (typeof batchExportSceneLogic)['props'] => ({
        id: id === 'new' ? null : id,
        service: service ? normalizeBatchExportService(service) : null,
    }),
}

function BatchExportSceneHeader({ logicProps }: { logicProps: BatchExportConfigurationLogicProps }): JSX.Element {
    const { configuration, batchExportConfigLoading } = useValues(batchExportConfigurationLogic(logicProps))
    const { setConfigurationValue, deleteBatchExport } = useActions(batchExportConfigurationLogic(logicProps))

    return (
        <>
            <SceneTitleSection
                name={configuration.name}
                description={null}
                // TODO: follow up at some point and add description support
                // description={configuration.description || ''}
                resourceType={{
                    type: 'data_pipelines',
                    forceIcon: configuration.destination ? (
                        <RenderBatchExportIcon size="medium" type={configuration.destination} />
                    ) : undefined,
                }}
                isLoading={batchExportConfigLoading}
                onNameChange={(value) => setConfigurationValue('name', value)}
                onDescriptionChange={(value) => setConfigurationValue('description', value)}
                canEdit
                actions={
                    <>
                        <More
                            size="small"
                            overlay={
                                <>
                                    <LemonButton status="danger" fullWidth onClick={() => deleteBatchExport()}>
                                        Delete
                                    </LemonButton>
                                </>
                            }
                        />
                        <LemonDivider vertical />
                        <BatchExportConfigurationClearChangesButton />
                        <BatchExportConfigurationSaveButton />
                    </>
                }
            />
        </>
    )
}

export function BatchExportScene(componentProps: any): JSX.Element {
    const { id, service: serviceParam } = componentProps
    const logicProps: BatchExportConfigurationLogicProps = {
        id: id ?? null,
        service: serviceParam ? normalizeBatchExportService(serviceParam) : null,
    }

    const logic = useMountedLogic(batchExportSceneLogic(logicProps))

    return <BatchExportSceneContent logic={logic} logicProps={logicProps} />
}

export function BatchExportSceneContent({
    logic,
    logicProps,
}: {
    logic: any
    logicProps: BatchExportConfigurationLogicProps
}): JSX.Element {
    const { currentTab } = useValues(logic)
    const { setCurrentTab } = useActions(logic)
    const { id, service } = logicProps

    const { batchExportConfig, loading } = useValues(batchExportConfigurationLogic(logicProps))

    if (loading && !batchExportConfig) {
        return (
            <div className="flex flex-col gap-4">
                <LemonSkeleton className="w-full h-12" />
                <HogFunctionSkeleton />
            </div>
        )
    }

    if (id && !batchExportConfig) {
        return <NotFound object="Batch export" />
    }

    if (service && !BATCH_EXPORT_SERVICE_NAMES.includes(service as BatchExportService['type'])) {
        return <NotFound object={`batch export service ${service}`} />
    }

    const tabs: (LemonTab<BatchExportSceneTab> | null)[] = [
        {
            label: 'Configuration',
            key: 'configuration',
            content: <BatchExportConfiguration />,
        },
        id
            ? {
                  label: 'Metrics',
                  key: 'metrics',
                  content: <BatchExportsMetrics id={id} />,
              }
            : null,
        id
            ? {
                  label: 'Logs',
                  key: 'logs',
                  content: (
                      <FlaggedFeature flag="batch-export-new-logs" fallback={<PipelineNodeLogs id={id} />}>
                          <LogsViewer sourceType="batch_exports" sourceId={id} instanceLabel="run" />
                      </FlaggedFeature>
                  ),
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

    return (
        <SceneContent>
            <BatchExportSceneHeader logicProps={logicProps} />
            <SceneDivider />
            <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} sceneInset />
        </SceneContent>
    )
}
