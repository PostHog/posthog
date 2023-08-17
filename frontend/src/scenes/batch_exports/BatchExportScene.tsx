import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonDivider, LemonTable, LemonTag } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { BatchExportLogicProps, batchExportLogic } from './batchExportLogic'
import { BatchExportRunIcon, BatchExportTag } from './components'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { IconEllipsis, IconRefresh } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, identifierToHuman } from 'lib/utils'
import { BatchExportBackfillModal } from './BatchExportBackfillModal'
import { humanizeDestination, intervalToFrequency, isRunInProgress } from './utils'
import { TZLabel } from '@posthog/apps-common'
import { Popover } from 'lib/lemon-ui/Popover'
import { LemonCalendarRange } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { NotFound } from 'lib/components/NotFound'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export const scene: SceneExport = {
    component: BatchExportScene,
    logic: batchExportLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }): BatchExportLogicProps => ({
        id: id ?? 'missing',
    }),
}

export function BatchExportScene(): JSX.Element {
    const {
        batchExportRunsResponse,
        batchExportConfig,
        batchExportConfigLoading,
        groupedRuns,
        batchExportRunsResponseLoading,
        runsDateRange,
    } = useValues(batchExportLogic)
    const {
        loadBatchExportConfig,
        loadBatchExportRuns,
        loadNextBatchExportRuns,
        openBackfillModal,
        setRunsDateRange,
        retryRun,
        pause,
        unpause,
        archive,
    } = useActions(batchExportLogic)

    const [dateRangeVisible, setDateRangeVisible] = useState(false)

    useEffect(() => {
        loadBatchExportConfig()
        loadBatchExportRuns()
    }, [])

    if (!batchExportConfig && !batchExportConfigLoading) {
        return <NotFound object={'Batch Export'} />
    }

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
                            <LemonMenu
                                items={[
                                    {
                                        label: batchExportConfig.paused ? 'Unpause' : 'Pause',
                                        onClick: () => {
                                            batchExportConfig.paused ? unpause() : pause()
                                        },
                                        disabledReason: batchExportConfigLoading ? 'Loading...' : undefined,
                                    },
                                    {
                                        label: 'Archive',
                                        status: 'danger',
                                        onClick: () =>
                                            LemonDialog.open({
                                                title: 'Archive Batch Export?',
                                                description:
                                                    'Are you sure you want to archive this Batch Export? This will stop all future runs',

                                                primaryButton: {
                                                    children: 'Archive',
                                                    status: 'danger',
                                                    onClick: () => archive(),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            }),
                                        disabledReason: batchExportConfigLoading ? 'Loading...' : undefined,
                                    },
                                ]}
                            >
                                <LemonButton icon={<IconEllipsis />} status="stealth" size="small" />
                            </LemonMenu>
                            <LemonDivider vertical />
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

            <div>
                {batchExportConfig ? (
                    <>
                        <div className="flex items-center gap-2">
                            <BatchExportTag batchExportConfig={batchExportConfig} />
                            <LemonTag>
                                {capitalizeFirstLetter(intervalToFrequency(batchExportConfig.interval))}
                            </LemonTag>

                            <LemonTag>
                                {batchExportConfig.end_at ? (
                                    <>
                                        <span className="flex gap-1">
                                            Ends <TZLabel time={batchExportConfig.end_at} />
                                        </span>
                                    </>
                                ) : (
                                    'Indefinite'
                                )}
                            </LemonTag>

                            <Tooltip
                                title={
                                    <>
                                        <ul className="mb-4">
                                            <li className="flex items-center justify-between gap-2">
                                                <span>Destination:</span>
                                                <span className="font-semibold">
                                                    {batchExportConfig.destination.type}
                                                </span>
                                            </li>

                                            {Object.keys(batchExportConfig.destination.config).map((x) => (
                                                <li key={x} className="flex items-center justify-between gap-2">
                                                    <span>{identifierToHuman(x)}:</span>
                                                    <span className="font-semibold">
                                                        {batchExportConfig.destination.config[x]}
                                                    </span>
                                                </li>
                                            ))}
                                        </ul>
                                    </>
                                }
                            >
                                <LemonTag>{humanizeDestination(batchExportConfig.destination)}</LemonTag>
                            </Tooltip>
                        </div>
                    </>
                ) : (
                    <LemonSkeleton className="w-10" />
                )}
            </div>

            {batchExportConfig ? (
                <div className="flex items-start mt-4 gap-8 flex-wrap">
                    <div className="flex-1 space-y-2">
                        <div className="flex justify-between items-start">
                            <h2 className="flex-1">Latest Runs</h2>
                            <Popover
                                actionable
                                onClickOutside={function noRefCheck() {
                                    setDateRangeVisible(false)
                                }}
                                visible={dateRangeVisible}
                                overlay={
                                    <LemonCalendarRange
                                        value={[runsDateRange.from, runsDateRange.to]}
                                        onChange={([start, end]) => {
                                            setRunsDateRange({ from: start.startOf('day'), to: end.endOf('day') })
                                            setDateRangeVisible(false)
                                        }}
                                        onClose={function noRefCheck() {
                                            setDateRangeVisible(false)
                                        }}
                                    />
                                }
                            >
                                <LemonButton
                                    onClick={function onClick() {
                                        setDateRangeVisible(!dateRangeVisible)
                                    }}
                                    type="secondary"
                                    status="stealth"
                                    size="small"
                                >
                                    {runsDateRange.from.format('MMMM D, YYYY')} -{' '}
                                    {runsDateRange.to.format('MMMM D, YYYY')}
                                </LemonButton>
                            </Popover>
                        </div>
                        <LemonTable
                            dataSource={groupedRuns}
                            loading={batchExportRunsResponseLoading}
                            loadingSkeletonRows={5}
                            footer={
                                batchExportRunsResponse?.next && (
                                    <div className="flex items-center m-2">
                                        <LemonButton
                                            center
                                            fullWidth
                                            onClick={loadNextBatchExportRuns}
                                            loading={batchExportRunsResponseLoading}
                                        >
                                            Load more button in the footer!
                                        </LemonButton>
                                    </div>
                                )
                            }
                            expandable={{
                                noIndent: true,
                                expandedRowRender: (groupedRuns) => {
                                    return (
                                        <LemonTable
                                            dataSource={groupedRuns.runs}
                                            embedded={true}
                                            size="small"
                                            columns={[
                                                {
                                                    title: 'Status',
                                                    key: 'status',
                                                    width: 0,
                                                    render: (_, run) => <BatchExportRunIcon runs={[run]} showLabel />,
                                                },
                                                {
                                                    title: 'ID',
                                                    key: 'runId',
                                                    render: (_, run) => run.id,
                                                },
                                                {
                                                    title: 'Run start',
                                                    key: 'runStart',
                                                    tooltip: 'Date and time when this BatchExport run started',
                                                    render: (_, run) => <TZLabel time={run.created_at} />,
                                                },
                                            ]}
                                        />
                                    )
                                },
                            }}
                            columns={[
                                {
                                    key: 'icon',
                                    width: 0,
                                    render: (_, groupedRun) => {
                                        return <BatchExportRunIcon runs={groupedRun.runs} />
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
                                                formatTime="HH:mm:ss"
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
                                                formatTime="HH:mm:ss"
                                            />
                                        )
                                    },
                                },
                                {
                                    title: 'Latest run start',
                                    key: 'runStart',
                                    tooltip: 'Date and time when this BatchExport run started',
                                    render: (_, groupedRun) => {
                                        return <TZLabel time={groupedRun.last_run_at} />
                                    },
                                },
                                {
                                    // title: 'Actions',
                                    key: 'actions',
                                    width: 0,
                                    render: function RenderName(_, groupedRun) {
                                        return (
                                            <span className="flex items-center gap-1">
                                                {!isRunInProgress(groupedRun.runs[0]) && (
                                                    <LemonButton
                                                        size="small"
                                                        type="secondary"
                                                        icon={<IconRefresh />}
                                                        onClick={() =>
                                                            LemonDialog.open({
                                                                title: 'Retry export?',
                                                                description: (
                                                                    <>
                                                                        <p>
                                                                            This will schedule a new run for the same
                                                                            interval. Any changes to the configuration
                                                                            will be applied to the new run.
                                                                        </p>
                                                                        <p>
                                                                            <b>Please note -</b> there may be a slight
                                                                            delay before the new run appears.
                                                                        </p>
                                                                    </>
                                                                ),
                                                                width: '20rem',
                                                                primaryButton: {
                                                                    children: 'Retry',
                                                                    onClick: () => retryRun(groupedRun.runs[0]),
                                                                },
                                                                secondaryButton: {
                                                                    children: 'Cancel',
                                                                },
                                                            })
                                                        }
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
                                        Create historic export
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
