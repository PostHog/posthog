import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { BatchExportLogicProps, batchExportLogic } from './batchExportLogic'
import { BatchExportRunIcon, BatchExportRunStatus, BatchExportTag } from './components'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { IconEdit, IconPause, IconRefresh } from 'lib/lemon-ui/icons'
import { identifierToHuman } from 'lib/utils'
import { BatchExportBackfillModal } from './BatchExportBackfillModal'
import { intervalToFrequency, isRunInProgress } from './utils'
import { TZLabel } from '@posthog/apps-common'
import { UUIDShortener } from 'lib/components/UUIDShortener'

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
    const { loadBatchExportConfig, loadBatchExportRuns, openBackfillModal } = useActions(batchExportLogic)

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
                            <LemonButton type="secondary" onClick={() => openBackfillModal()}>
                                Create historic export
                            </LemonButton>

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
                        <LemonTag className="uppercase">{intervalToFrequency(batchExportConfig.interval)}</LemonTag>
                    </>
                ) : (
                    <LemonSkeleton className="w-10" />
                )}
            </div>

            {batchExportConfig ? (
                <div className="flex items-start mt-4 gap-8 flex-wrap">
                    <div className="shrink-0 min-w-60">
                        <h2>Configuration</h2>

                        <ul className="mb-4">
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

                        <LemonButton
                            icon={<IconEdit />}
                            type="secondary"
                            to={urls.batchExportEdit(batchExportConfig.id)}
                        >
                            Edit
                        </LemonButton>
                    </div>

                    <div className="flex-1">
                        <h2>Latest Runs</h2>
                        <LemonTable
                            dataSource={batchExportRuns?.results ?? []}
                            loading={batchExportRunsLoading}
                            loadingSkeletonRows={5}
                            pagination={batchExportRunsPagination}
                            columns={[
                                {
                                    key: 'icon',
                                    width: 0,
                                    render: (_, run) => {
                                        return <BatchExportRunIcon batchExportRun={run} />
                                    },
                                },
                                {
                                    title: 'ID',
                                    key: 'runId',
                                    width: 0,
                                    render: (_, run) => {
                                        return (
                                            <Link
                                                className="font-semibold"
                                                to={urls.batchExport(batchExportConfig.id, {
                                                    runId: run.id,
                                                })}
                                            >
                                                <UUIDShortener uuid={run.id} />
                                            </Link>
                                        )
                                    },
                                },

                                {
                                    title: 'Data interval start',
                                    key: 'dataIntervalStart',
                                    tooltip: 'Start of the time range to export',
                                    render: (_, run) => {
                                        return (
                                            <TZLabel
                                                time={run.data_interval_start}
                                                formatDate="MMMM DD, YYYY"
                                                formatTime="hh:mm:ss"
                                            />
                                        )
                                    },
                                },
                                {
                                    title: 'Data interval end',
                                    key: 'dataIntervalEnd',
                                    tooltip: 'End of the time range to export',
                                    render: (_, run) => {
                                        return (
                                            <TZLabel
                                                time={run.data_interval_end}
                                                formatDate="MMMM DD, YYYY"
                                                formatTime="hh:mm:ss"
                                            />
                                        )
                                    },
                                },
                                {
                                    title: 'Run start',
                                    key: 'runStart',
                                    tooltip: 'Date and time when this BatchExport run started',
                                    render: (_, run) => {
                                        return <TZLabel time={run.created_at} />
                                    },
                                },
                                {
                                    // title: 'Actions',
                                    key: 'actions',
                                    width: 0,
                                    render: function RenderName(_, run) {
                                        return (
                                            <span className="flex items-center gap-1">
                                                {isRunInProgress(run) ? (
                                                    <LemonButton
                                                        size="small"
                                                        type="secondary"
                                                        icon={<IconPause />}
                                                        onClick={() => alert('TODO')}
                                                    />
                                                ) : (
                                                    <LemonButton
                                                        size="small"
                                                        type="secondary"
                                                        icon={<IconRefresh />}
                                                        onClick={() => alert('TODO')}
                                                    />
                                                )}
                                            </span>
                                        )
                                    },
                                },
                            ]}
                            emptyState={
                                <>
                                    No runs yet. Your exporter runs every <b>{batchExportConfig.interval}</b>.
                                    <br />
                                    <LemonButton type="primary" onClick={() => openBackfillModal()}>
                                        Schedule historic export
                                    </LemonButton>
                                </>
                            }
                        />
                    </div>
                </div>
            ) : null}

            <BatchExportBackfillModal />
        </>
    )
}
