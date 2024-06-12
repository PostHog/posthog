import { TZLabel } from '@posthog/apps-common'
import { IconEllipsis } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonTable,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarRange } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Popover } from 'lib/lemon-ui/Popover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, identifierToHuman } from 'lib/utils'
import { pluralize } from 'lib/utils'
import { useEffect, useState } from 'react'
import { BatchExportRunsGrouped } from 'scenes/pipeline/BatchExportRuns'
import { PipelineLogLevel } from 'scenes/pipeline/pipelineNodeLogsLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BatchExportLogEntry } from '~/types'

import { BatchExportBackfillModal } from './BatchExportBackfillModal'
import { batchExportLogic, BatchExportLogicProps, BatchExportTab } from './batchExportLogic'
import { batchExportLogsLogic, BatchExportLogsProps, LOGS_PORTION_LIMIT } from './batchExportLogsLogic'
import { BatchExportTag } from './components'
import { humanizeDestination, intervalToFrequency, showBatchExports } from './utils'

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
        return <NotFound object="Batch Export" />
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
                                    size="small"
                                >
                                    {runsDateRange.from.format('MMMM D, YYYY')} -{' '}
                                    {runsDateRange.to.format('MMMM D, YYYY')}
                                </LemonButton>
                            </Popover>
                        </div>
                        <BatchExportRunsGrouped
                            groupedRuns={groupedRuns}
                            loading={batchExportRunsResponseLoading}
                            retryRun={retryRun}
                            hasMoreRunsToLoad={!!batchExportRunsResponse?.next}
                            loadOlderRuns={loadNextBatchExportRuns}
                            interval={batchExportConfig.interval}
                            openBackfillModal={openBackfillModal}
                        />
                    </div>
                </div>
            ) : null}
        </>
    )
}

function BatchExportLogEntryLevelDisplay(type: PipelineLogLevel): JSX.Element {
    let color: string | undefined
    switch (type) {
        case PipelineLogLevel.Debug:
            color = 'var(--muted)'
            break
        case PipelineLogLevel.Log:
            color = 'var(--text-3000)'
            break
        case PipelineLogLevel.Info:
            color = 'var(--blue)'
            break
        case PipelineLogLevel.Warning:
            color = 'var(--warning)'
            break
        case PipelineLogLevel.Error:
            color = 'var(--danger)'
            break
        default:
            break
    }
    // eslint-disable-next-line react/forbid-dom-props
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

    const logic = batchExportLogsLogic({ batchExportId })
    const {
        batchExportLogs,
        batchExportLogsLoading,
        batchExportLogsBackground,
        isThereMoreToLoad,
        batchExportLogsTypes,
    } = useValues(logic)
    const { revealBackground, loadBatchExportLogsMore, setBatchExportLogsTypes, setSearchTerm } = useActions(logic)

    if (!batchExportConfig || batchExportConfigLoading || !activeTab) {
        return <LemonSkeleton />
    }

    return (
        <div className="ph-no-capture space-y-2 flex-1">
            <LemonInput
                type="search"
                placeholder="Search for messages containing…"
                fullWidth
                onChange={setSearchTerm}
                allowClear
            />
            <div className="flex items-center gap-4">
                <span>Show logs of type:&nbsp;</span>
                {Object.values(PipelineLogLevel).map((type) => {
                    return (
                        <LemonCheckbox
                            key={type}
                            label={type}
                            checked={batchExportLogsTypes.includes(type)}
                            onChange={(checked) => {
                                const newBatchExportLogsTypes = checked
                                    ? [...batchExportLogsTypes, type]
                                    : batchExportLogsTypes.filter((t) => t != type)
                                setBatchExportLogsTypes(newBatchExportLogsTypes)
                            }}
                        />
                    )
                })}
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
                    disabledReason={!isThereMoreToLoad ? "There's nothing more to load" : undefined}
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
    const hasDataPipelines = showBatchExports()

    useEffect(() => {
        loadBatchExportConfig()
        loadBatchExportRuns()
    }, [])

    if (!batchExportConfig && !batchExportConfigLoading) {
        return <NotFound object="Batch Export" />
    }

    return (
        <>
            <PageHeader
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
                                <LemonButton icon={<IconEllipsis />} size="small" />
                            </LemonMenu>
                            {hasDataPipelines && (
                                <>
                                    <LemonDivider vertical />
                                    <LemonButton type="secondary" onClick={() => openBackfillModal()}>
                                        Create historic export
                                    </LemonButton>
                                </>
                            )}

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
                    <LemonSkeleton className="w-10 h-4" />
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
