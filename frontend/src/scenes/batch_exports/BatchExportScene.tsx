import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonLabel, LemonTable } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { BatchExportLogicProps, batchExportLogic } from './batchExportLogic'
import { BatchExportTag } from './components'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { IconEdit } from 'lib/lemon-ui/icons'
import { identifierToHuman } from 'lib/utils'

export const scene: SceneExport = {
    component: BatchExportScene,
    logic: batchExportLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }): BatchExportLogicProps => ({
        id: id ?? 'missing',
    }),
}

export function BatchExportScene(): JSX.Element {
    const {
        batchExportConfig,
        batchExportConfigLoading,
        batchExportRuns,
        batchExportRunsLoading,
        batchExportRunsPagination,
    } = useValues(batchExportLogic)
    const { loadBatchExportConfig, loadBatchExportRuns } = useActions(batchExportLogic)

    useEffect(() => {
        loadBatchExportConfig()
        loadBatchExportRuns()
    }, [])

    return (
        <>
            <PageHeader
                title={
                    <span className="flex items-center gap-2">
                        {batchExportConfig?.name ?? (batchExportConfigLoading ? 'Loading...' : 'Missing')}
                    </span>
                }
                buttons={
                    batchExportConfig ? (
                        <>
                            <LemonButton type="primary" to={urls.batchExportEdit(batchExportConfig?.id)}>
                                Edit
                            </LemonButton>
                        </>
                    ) : undefined
                }
            />

            <div className="flex items-center gap-2">
                {batchExportConfig ? (
                    <>
                        <BatchExportTag batchExportConfig={batchExportConfig} />
                    </>
                ) : (
                    <LemonSkeleton className="w-10" />
                )}
            </div>

            {batchExportConfig ? (
                <div className="flex items-start mt-4 gap-4 flex-wrap">
                    <div className="shrink-0 min-w-60 border rounded p-3">
                        <div className="flex justify-between items-center">
                            <LemonLabel>Configuration</LemonLabel>

                            <LemonButton
                                icon={<IconEdit />}
                                size="small"
                                to={urls.batchExportEdit(batchExportConfig.id)}
                            >
                                Edit
                            </LemonButton>
                        </div>

                        <ul>
                            <li className="flex items-center justify-between gap-2">
                                <span>Destination:</span>
                                <span className="font-semibold">{batchExportConfig.destination.type}</span>
                            </li>

                            {Object.keys(batchExportConfig.destination.config).map((x) => (
                                <li key={x} className="flex items-center justify-between gap-2">
                                    <span>{identifierToHuman(x)}:</span>
                                    <span className="font-semibold">{batchExportConfig.destination.config[x]}</span>
                                </li>
                            ))}
                        </ul>
                    </div>

                    <div className="flex-1">
                        <LemonTable
                            dataSource={batchExportRuns?.results ?? []}
                            loading={batchExportRunsLoading}
                            loadingSkeletonRows={5}
                            pagination={batchExportRunPagination}
                            columns={[
                                {
                                    title: 'Status',
                                    key: 'status',
                                    render: function RenderStatus(_, run) {
                                        return 'wat'
                                    },
                                },
                                {
                                    title: 'ID',
                                    key: 'runId',
                                    render: function RenderStatus(_, run) {
                                        return <>{run.id}</>
                                    },
                                },
                                {
                                    title: 'Run start',
                                    key: 'runStart',
                                    tooltip: 'Date and time when this BatchExport run started',
                                    render: function RenderName(_, run) {
                                        return 'wat'
                                        // return <>{dayjs(run.created_at).format('YYYY-MM-DD HH:mm:ss z')}</>
                                    },
                                },
                            ]}
                        />
                    </div>
                </div>
            ) : null}
        </>
    )
}
