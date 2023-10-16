import { Checkbox } from 'antd'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonDivider, LemonTable, LemonTag, LemonInput, LemonTableColumns } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { BatchExportLogicProps, batchExportLogic, BatchExportTab } from './batchExportLogic'
import { BatchExportLogsProps, batchExportLogsLogic, LOGS_PORTION_LIMIT } from './batchExportLogsLogic'
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
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { dayjs } from 'lib/dayjs'
import { BatchExportLogEntryLevel, BatchExportLogEntry } from '~/types'
import { pluralize } from 'lib/utils'

export const scene: SceneExport = {
    component: BatchExportScene,
    logic: batchExportLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }): BatchExportLogicProps => ({
        id: id ?? 'missing',
    }),
}

export function RunsTab(): JSX.Element {
    const {
        batchExportRunsResponse,
        batchExportConfig,
        groupedRuns,
        batchExportRunsResponseLoading,
        runsDateRange,
        batchExportConfigLoading,
    } = useValues(batchExportLogic)
    const { loadNextBatchExportRuns, openBackfillModal, setRunsDateRange, retryRun } = useActions(batchExportLogic)

    const [dateRangeVisible, setDateRangeVisible] = useState(false)

    if (!batchExportConfig && !batchExportConfigLoading) {
        return <NotFound object={'Batch Export'} />
    }

    return (
        <>
            {batchExportConfig ? (
                <div className="flex items-start gap-8 flex-wrap">
                    <div className="flex-1 space-y-2">
                        <div className="flex justify-end items-start">
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
        </>
    )
}

function BatchExportLogEntryLevelDisplay(type: BatchExportLogEntryLevel): JSX.Element {
    let color: string | undefined
    switch (type) {
        case BatchExportLogEntryLevel.Debug:
            color = 'var(--muted)'
            break
        case BatchExportLogEntryLevel.Log:
            color = 'var(--default)'
            break
        case BatchExportLogEntryLevel.Info:
            color = 'var(--blue)'
            break
        case BatchExportLogEntryLevel.Warning:
            color = 'var(--warning)'
            break
        case BatchExportLogEntryLevel.Error:
            color = 'var(--danger)'
            break
        default:
            break
    }
    return <span style={{ color }}>{type}</span>
}

const columns: LemonTableColumns<BatchExportLogEntry> = [
    {
        title: 'Timestamp',
        key: 'timestamp',
        dataIndex: 'timestamp',
        width: 1,
        render: (_, entry: BatchExportLogEntry) => dayjs(entry.timestamp).format('YYYY-MM-DD HH:mm:ss.SSS UTC'),
    },
    {
        title: 'Level',
        key: 'level',
        dataIndex: 'level',
        width: 1,
        render: (_, entry: BatchExportLogEntry) => BatchExportLogEntryLevelDisplay(entry.level),
    },
    {
        title: 'Run ID',
        key: 'run_id',
        dataIndex: 'run_id',
        width: 1,
        render: (_, entry) => entry.run_id,
    },
    {
        title: 'Message',
        key: 'message',
        dataIndex: 'message',
        width: 6,
    },
]

export function LogsTab({ batchExportId }: BatchExportLogsProps): JSX.Element {
    const { activeTab, batchExportConfig, batchExportConfigLoading } = useValues(batchExportLogic)

    if (!batchExportConfig || batchExportConfigLoading || !activeTab) {
        return <LemonSkeleton />
    }

    const logic = batchExportLogsLogic({ batchExportId })
    const {
        batchExportLogs,
        batchExportLogsLoading,
        batchExportLogsBackground,
        isThereMoreToLoad,
        batchExportLogsTypes,
    } = useValues(logic)
    const { revealBackground, loadBatchExportLogsMore, setBatchExportLogsTypes, setSearchTerm } = useActions(logic)

    return (
        <div className="ph-no-capture space-y-2 flex-1">
            <LemonInput
                type="search"
                placeholder="Search for messages containing…"
                fullWidth
                onChange={setSearchTerm}
                allowClear
            />
            <div className="flex items-center gap-2">
                <span>Show logs of type:&nbsp;</span>
                <Checkbox.Group
                    options={Object.values(BatchExportLogEntryLevel)}
                    value={batchExportLogsTypes}
                    onChange={setBatchExportLogsTypes}
                    style={{ marginLeft: '8px' }}
                />
            </div>
            <LemonButton
                onClick={revealBackground}
                loading={batchExportLogsLoading}
                type="secondary"
                fullWidth
                center
                disabledReason={!batchExportLogsBackground.length ? "There's nothing to load" : undefined}
            >
                {batchExportLogsBackground.length
                    ? `Load ${pluralize(batchExportLogsBackground.length, 'newer entry', 'newer entries')}`
                    : 'No new entries'}
            </LemonButton>
            <LemonTable
                dataSource={batchExportLogs}
                columns={columns}
                loading={batchExportLogsLoading}
                size="small"
                className="ph-no-capture"
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
            {!!batchExportLogs.length && (
                <LemonButton
                    onClick={loadBatchExportLogsMore}
                    loading={batchExportLogsLoading}
                    type="secondary"
                    fullWidth
                    center
                    disabledReason={!isThereMoreToLoad ? "There's nothing mote to load" : undefined}
                >
                    {isThereMoreToLoad ? `Load up to ${LOGS_PORTION_LIMIT} older entries` : 'No older entries'}
                </LemonButton>
            )}
        </div>
    )
}

export function BatchExportScene(): JSX.Element {
    const { batchExportConfig, batchExportConfigLoading, activeTab } = useValues(batchExportLogic)
    const { loadBatchExportConfig, loadBatchExportRuns, openBackfillModal, pause, unpause, archive, setActiveTab } =
        useActions(batchExportLogic)

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

                                            {Object.keys(batchExportConfig.destination.config)
                                                .filter(
                                                    (x) =>
                                                        ![
                                                            'password',
                                                            'aws_secret_access_key',
                                                            'client_email',
                                                            'token_uri',
                                                            'private_key',
                                                            'private_key_id',
                                                        ].includes(x)
                                                )
                                                .map((x) => (
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

            {batchExportConfig && activeTab ? (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(newKey) => setActiveTab(newKey)}
                    tabs={[
                        {
                            key: BatchExportTab.Runs,
                            label: <>Latest runs</>,
                            content: <RunsTab />,
                        },
                        {
                            key: BatchExportTab.Logs,
                            label: <>Logs</>,
                            content: <LogsTab batchExportId={batchExportConfig.id} />,
                        },
                    ]}
                />
            ) : null}

            <BatchExportBackfillModal />
        </>
    )
}
