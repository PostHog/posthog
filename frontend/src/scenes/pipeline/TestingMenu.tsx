import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonTable,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { AvailableFeature, BatchExportRun } from '~/types'

import { hogFunctionConfigurationLogic } from './hogfunctions/hogFunctionConfigurationLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { IconRefresh } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import dayjs, { Dayjs } from 'dayjs'

export interface HogFunctionConfigurationProps {
    templateId?: string | null
    id?: string | null

    displayOptions?: {
        embedded?: boolean
        hidePageHeader?: boolean
        hideOverview?: boolean
        showFilters?: boolean
        showExpectedVolume?: boolean
        showStatus?: boolean
        showEnabled?: boolean
        showTesting?: boolean
        canEditSource?: boolean
        showPersonsCount?: boolean
    }
}

export function TestingMenu({
    templateId,
    id,
    displayOptions = {},
}: HogFunctionConfigurationProps): JSX.Element {
    const logicProps = { templateId, id }
    const logic = hogFunctionConfigurationLogic(logicProps)
    const {
        isConfigurationSubmitting,
        configurationChanged,
        configuration,
        loading,
        loaded,
        hogFunction,
        willReEnableOnSave,
        willChangeEnabledOnSave,
        showPaygate,
        template,
        type,
    } = useValues(logic)
    const {
        submitConfiguration,
        resetForm,
        duplicate,
        deleteHogFunction,
    } = useActions(logic)

    if (loading && !loaded) {
        return <SpinnerOverlay />
    }

    if (!loaded) {
        return <NotFound object="Hog function" />
    }

    const isLegacyPlugin = (template?.id || hogFunction?.template?.id)?.startsWith('plugin-')

    const headerButtons = (
        <>
            {!templateId && (
                <>
                    <More
                        overlay={
                            <>
                                {!isLegacyPlugin && (
                                    <LemonButton fullWidth onClick={() => duplicate()}>
                                        Duplicate
                                    </LemonButton>
                                )}
                                <LemonDivider />
                                <LemonButton status="danger" fullWidth onClick={() => deleteHogFunction()}>
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                    <LemonDivider vertical />
                </>
            )}
        </>
    )

    const saveButtons = (
        <>
            {configurationChanged ? (
                <LemonButton
                    type="secondary"
                    htmlType="reset"
                    onClick={() => resetForm()}
                    disabledReason={
                        !configurationChanged
                            ? 'No changes'
                            : isConfigurationSubmitting
                            ? 'Saving in progress…'
                            : undefined
                    }
                >
                    Clear changes
                </LemonButton>
            ) : null}
            <LemonButton
                type="primary"
                htmlType="submit"
                onClick={submitConfiguration}
                loading={isConfigurationSubmitting}
            >
                {templateId ? 'Create' : 'Save'}
                {willReEnableOnSave
                    ? ' & re-enable'
                    : willChangeEnabledOnSave
                    ? ` & ${configuration.enabled ? 'enable' : 'disable'}`
                    : ''}
            </LemonButton>
        </>
    )

    if (showPaygate) {
        return <PayGateMini feature={AvailableFeature.DATA_PIPELINES} />
    }

    const includeHeaderButtons = !(displayOptions.hidePageHeader ?? false)
    const showExpectedVolume = displayOptions.showExpectedVolume ?? ['destination', 'site_destination'].includes(type)

    return (
        <div className="space-y-3">
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
                {includeHeaderButtons && (
                    <PageHeader
                        buttons={
                            <>
                                {headerButtons}
                                {saveButtons}
                            </>
                        }
                    />
                )}

                {hogFunction?.filters?.bytecode_error ? (
                    <div>
                        <LemonBanner type="error">
                            <b>Error saving filters:</b> {hogFunction.filters.bytecode_error}
                        </LemonBanner>
                    </div>
                ) : null}

                {showExpectedVolume ? <HogFunctionEventEstimates /> : null}
            </BindLogic>
        </div>
    )
}

function RunResult({ run }: { run: any }): JSX.Element {
    const testResult = run.retries[0]

    return (
        <div className="space-y-2" data-attr="test-results">
            <LemonTable
                dataSource={testResult.logs ?? []}
                columns={[
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'timestamp',
                        render: (timestamp) => <TZLabel time={timestamp as string} />,
                        width: 0,
                    },
                    {
                        width: 100,
                        title: 'Level',
                        key: 'level',
                        dataIndex: 'level',
                    },
                    {
                        title: 'Message',
                        key: 'message',
                        dataIndex: 'message',
                        render: (message) => <code className="whitespace-pre-wrap">{message}</code>,
                    },
                ]}
                className="ph-no-capture"
                rowKey="timestamp"
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
        </div>
    )
}

function RunRetryButton({ run, retryRun }: { run: any; retryRun: any }): JSX.Element {
    const handleRetry = () => {
        LemonDialog.open({
            title: 'Resend event?',
            description: (
                <>  
                    <p>
                        This will schedule a new run for the same interval. Any changes to the configuration
                        will be applied to the new run.
                    </p>
                    <p>
                        <b>Please note -</b> there may be a slight delay before the new run appears.
                    </p>
                </>
            ),
            width: '20rem',
            primaryButton: {
                children: 'Retry',
                onClick: () => retryRun(run),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <span className="flex items-center gap-1">
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconRefresh />}
                onClick={handleRetry}
            />
        </span>
    )
}

export function BatchExportRunIcon({
    runs,
    showLabel = false,
}: {
    runs: any[]
    showLabel?: boolean
}): JSX.Element {
    // We assume these are pre-sorted
    const latestRun = runs[0]

    const status = combineFailedStatuses(latestRun.status)
    const color = colorForStatus(status)

    return (
        <Tooltip
            title={
                <>
                    Run status: {status}
                    {runs.length > 1 && (
                        <>
                            <br />
                            Attempts: {runs.length}
                        </>
                    )}
                </>
            }
        >
            <span
                className={clsx(
                    `BatchExportRunIcon h-6 p-2 border-2 flex items-center justify-center rounded-full font-semibold text-xs border-${color} text-${color}-dark select-none`,
                    color === 'primary' && 'BatchExportRunIcon--pulse',
                    showLabel ? '' : 'w-6'
                )}
            >
                {showLabel ? <span className="text-center">{status}</span> : runs.length}
            </span>
        </Tooltip>
    )
}

export function HogFunctionEventEstimates(): JSX.Element | null {
    const { eventsDataTableNode } = useValues(hogFunctionConfigurationLogic)

    if (!eventsDataTableNode) {
        return null
    }

    const groupedRuns: {
        last_run_at: Dayjs
        data_interval_start: Dayjs
        data_interval_end: Dayjs
        runs: {
            id: string
            event: string
            person: string
            url: string
            library: string
            time: Dayjs
            status: 'Cancelled' | 'Completed' | 'ContinuedAsNew' | 'Failed' | 'FailedRetryable' | 'Terminated' | 'TimedOut' | 'Running' | 'Starting'
            retries: {
                result: any
                status: string
                errors: any[]
                logs: {
                    level: string
                    timestamp: string
                    message: string
                }[]
            }[]
        }[]
    }[] = [
        {
            runs: [
                {
                    id: '1',
                    event: '$pageview',
                    person: '12345',
                    url: 'https://posthog.com',
                    library: 'js',
                    time: dayjs('2024-01-01'),
                    status: 'Completed',
                    retries: [
                        {
                            result: null,
                            status: 'success',
                            errors: [],
                            logs: [
                                {
                                    level: 'debug',
                                    timestamp: '2025-02-18T11:44:50.595+01:00',
                                    message: 'Executing function'
                                },
                                {
                                    level: 'debug',
                                    timestamp: '2025-02-18T11:44:50.595+01:00',
                                    message: "Suspending function due to async function call 'fetch'. Payload: 3359 bytes. Event: 3bb7b102-13d4-4274-807c-e8cc9f3634d5"
                                },
                                {
                                    level: 'error',
                                    timestamp: '2025-02-18T11:44:52.118+01:00',
                                    message: 'Fetch failed after 1 attempts'
                                },
                                {
                                    level: 'warn',
                                    timestamp: '2025-02-18T11:44:52.118+01:00',
                                    message: 'Fetch failure of kind failurestatus with status 429 and message Received failure status'
                                },
                                {
                                    level: 'debug',
                                    timestamp: '2025-02-18T11:44:52.118+01:00',
                                    message: 'Resuming function'
                                },
                                {
                                    level: 'debug',
                                    timestamp: '2025-02-18T11:44:52.118+01:00',
                                    message: 'Function completed in 1522.232748746872ms. Sync: 0ms. Mem: 1838 bytes. Ops: 28. Event: http://localhost:8010/project/1/events/'
                                }
                            ]
                        }
                    ]
                },
            ],
            last_run_at: dayjs('2024-01-01'),
            data_interval_start: dayjs('2024-01-01'),
            data_interval_end: dayjs('2024-01-01'),
        },
        {
            runs: [
                {
                    id: '2',
                    event: '$pageview',
                    person: '12345',
                    url: 'https://posthog.com/pricing',
                    library: 'js',
                    time: dayjs('2024-01-01'),
                    status: 'Completed',
                    retries: [
                        {
                            result: null,
                            status: 'success',
                            errors: [],
                            logs: []
                        }
                    ]
                },
            ],
            last_run_at: dayjs('2024-01-01'),
            data_interval_start: dayjs('2024-01-01'),
            data_interval_end: dayjs('2024-01-01'),
        },
    ]
    const loading = false
    const hasMoreRunsToLoad = false
    const loadOlderRuns = () => {}
    const retryRun = () => {}
    const canEnableNewDestinations = false
    const openBackfillModal = () => {}
    const interval = '1 hour'

    return (
        <>
            {eventsDataTableNode && (
                <>
                    {/* <Query
                        query={{
                            ...eventsDataTableNode,
                            full: false,
                            showEventFilter: false,
                            showPropertyFilter: false,
                            embedded: true,
                            showOpenEditorButton: false,
                            showHogQLEditor: false,
                            showTimings: false,
                        }}
                    /> */}
                    <LemonTable
                        dataSource={groupedRuns}
                        loading={loading}
                        loadingSkeletonRows={5}
                        footer={
                            hasMoreRunsToLoad && (
                                <div className="flex items-center m-2">
                                    <LemonButton center fullWidth onClick={loadOlderRuns} loading={loading}>
                                        Load more rows
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
                                        columns={[
                                            {
                                                title: 'Status',
                                                key: 'status',
                                                width: 0,
                                                render: (_, run) => {
                                                    const testResult = run.retries[0]

                                                    return false ? (
                                                        <LemonBanner type={testResult.status === 'success' ? 'success' : 'error'}>
                                                            {testResult.status === 'success' ? 'Success' : 'Error'}
                                                        </LemonBanner>
                                                    ) : <BatchExportRunIcon runs={[run]} showLabel />
                                                }
                                            },
                                            {
                                                title: 'ID',
                                                key: 'runId',
                                                render: (_, run) => run.id,
                                            },
                                            {
                                                title: 'Test invocation logs',
                                                key: 'testInvocationLogs',
                                                render: (_, run) => <RunResult run={run} />,
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
                                title: 'Event',
                                key: 'event',
                                render: (_, groupedRun) => {
                                    return (
                                        <span>
                                            {groupedRun.runs[0].event}
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Person',
                                key: 'person',
                                render: (_, groupedRun) => {
                                    return (
                                        <span>
                                            {groupedRun.runs[0].person}
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Url',
                                key: 'url',
                                render: (_, groupedRun) => {
                                    return (
                                        <span>
                                            {groupedRun.runs[0].url}
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Library',
                                key: 'library',
                                render: (_, groupedRun) => {
                                    return (
                                        <span>
                                            {groupedRun.runs[0].library}
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Time',
                                key: 'time',
                                render: (_, groupedRun) => {
                                    return <TZLabel time={groupedRun.runs[0].time} />
                                },
                            },
                            {
                                key: 'actions',
                                width: 0,
                                render: function RenderActions(_, run) {
                                    return (
                                        <div className="flex gap-1">
                                            <RunRetryButton run={run} retryRun={retryRun} />
                                        </div>
                                    )
                                },
                            },
                        ]}
                        emptyState={
                            <div className="space-y-2">
                                <div>
                                    No runs in this time range. Your exporter runs every <b>{interval}</b>.
                                </div>
                                {canEnableNewDestinations && (
                                    <LemonButton type="primary" onClick={() => openBackfillModal()}>
                                        Start backfill
                                    </LemonButton>
                                )}
                            </div>
                        }
                    />
                </>
            )}
        </>
    )
}

const combineFailedStatuses = (status: BatchExportRun['status']): BatchExportRun['status'] => {
    // Eventually we should expose the difference between "Failed" and "FailedRetryable" to the user,
    // because "Failed" tends to mean their configuration or destination is broken.
    if (status === 'FailedRetryable') {
        return 'Failed'
    }
    return status
}

const colorForStatus = (status: BatchExportRun['status']): 'success' | 'primary' | 'warning' | 'danger' | 'default' => {
    switch (status) {
        case 'Completed':
            return 'success'
        case 'ContinuedAsNew':
        case 'Running':
        case 'Starting':
            return 'primary'
        case 'Cancelled':
        case 'Terminated':
        case 'TimedOut':
            return 'warning'
        case 'Failed':
        case 'FailedRetryable':
            return 'danger'
        default:
            return 'default'
    }
}