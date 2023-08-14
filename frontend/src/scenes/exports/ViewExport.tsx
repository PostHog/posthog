import { dayjs } from 'lib/dayjs'
import { useValues } from 'kea'
import { useCurrentTeamId, useExport, useExportRuns, BatchExport, BatchExportRun, useExportRunAction } from './api'
import { PageHeader } from 'lib/components/PageHeader'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconReplay } from 'lib/lemon-ui/icons'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonCalendarRange } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRange'
import { InlineExportActionButtons } from './ExportsList'
import { LemonTable } from '../../lib/lemon-ui/LemonTable'
import { router } from 'kea-router'
import { useState } from 'react'
import clsx from 'clsx'
import { Spinner } from 'lib/lemon-ui/Spinner'

export const Export = (): JSX.Element => {
    // Displays a single export. We use the useCurrentTeamId hook to get the
    // current team ID, and then use the useExport hook to fetch the export
    // details for that team. We pull out the export_id from the URL.
    const { currentLocation } = useValues(router)
    const exportId = currentLocation.pathname.split('/').pop()

    if (exportId === undefined) {
        throw Error('exportId is undefined')
    }

    const { currentTeamId } = useCurrentTeamId()
    const { loading, export_, error, updateCallback } = useExport(currentTeamId, exportId)

    // If the export is still undefined and we're loading, show a loading
    // message and placeholder.
    if (export_ === undefined) {
        return (
            <div>
                <h1>Export</h1>
                <p>
                    <Spinner /> Fetching export...
                </p>
            </div>
        )
    }

    // If we have an error, show the error message.
    if (error) {
        return (
            <div>
                <h1>Export</h1>
                <p>Error fetching export: {error}</p>
            </div>
        )
    }

    // If we have an export, show the export details.
    return (
        <>
            <ExportHeader
                currentTeamId={currentTeamId}
                export_={export_}
                loading={loading}
                updateCallback={updateCallback}
            />

            {loading ? <p>Loading...</p> : null}

            <ExportRuns exportId={exportId} />
        </>
    )
}

export interface ExportHeaderProps {
    currentTeamId: number
    export_: BatchExport
    loading: boolean
    updateCallback: (signal: AbortSignal | undefined) => void
}

function ExportHeader({ currentTeamId, export_, loading, updateCallback }: ExportHeaderProps): JSX.Element {
    return (
        <>
            <PageHeader
                title={
                    <div className="flex items-center gap-2 mb-2">
                        {export_.name}
                        <CopyToClipboardInline explicitValue={export_.name} iconStyle={{ color: 'var(--muted-alt)' }} />
                        <div className="flex gap-2">
                            {export_.paused ? (
                                <LemonTag type="default" className="uppercase">
                                    Paused
                                </LemonTag>
                            ) : (
                                <LemonTag type="primary" className="uppercase">
                                    Running
                                </LemonTag>
                            )}
                            <LemonTag type="default">{export_.destination.type}</LemonTag>
                            <LemonTag type="default">Frequency: {export_.interval}</LemonTag>
                        </div>
                    </div>
                }
                buttons={
                    <InlineExportActionButtons
                        currentTeamId={currentTeamId}
                        export_={export_}
                        loading={loading}
                        updateCallback={updateCallback}
                    />
                }
            />
        </>
    )
}

const ExportRunStatus = ({ exportRun }: { exportRun: BatchExportRun }): JSX.Element => {
    if (exportRun.status === 'Running') {
        return (
            <LemonTag type="primary" className="uppercase">
                Running
            </LemonTag>
        )
    } else if (exportRun.status === 'Completed') {
        return (
            <LemonTag type="success" className="uppercase">
                Completed
            </LemonTag>
        )
    } else if (exportRun.status === 'Starting') {
        return (
            <LemonTag type="default" className="uppercase">
                Starting
            </LemonTag>
        )
    } else {
        return (
            <LemonTag type="danger" className="uppercase">
                Error
            </LemonTag>
        )
    }
}

type ExportRunKey = {
    workflow_id: string
}

function endOfDay(d: dayjs.Dayjs): dayjs.Dayjs {
    return d.hour(23).second(59).minute(59)
}

function startOfDay(d: dayjs.Dayjs): dayjs.Dayjs {
    return d.hour(0).second(0).minute(0)
}

const ExportRuns = ({ exportId }: { exportId: string }): JSX.Element => {
    // Displays a list of export runs for the given export ID. We use the
    // useCurrentTeamId hook to get the current team ID, and then use the
    // useExportRuns hook to fetch the export runs for that team and export ID.
    const defaultDateRange: [dayjs.Dayjs, dayjs.Dayjs] = [startOfDay(dayjs().subtract(1, 'day')), endOfDay(dayjs())]
    const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>(defaultDateRange)
    const [dateRangeVisible, setDateRangeVisible] = useState<boolean>(false)

    const defaultNumberOfRuns = 25
    const [numberOfRuns, setNumberOfRuns] = useState<number>(defaultNumberOfRuns)
    const { currentTeamId } = useCurrentTeamId()
    const { loading, exportRuns, error, updateCallback } = useExportRuns(
        currentTeamId,
        exportId,
        defaultNumberOfRuns,
        dateRange
    )
    // If the export runs are still undefined and we're loading, show a loading
    // message and placeholder.
    if (exportRuns === undefined) {
        return (
            <div>
                <h1>Export Runs</h1>
                <p>Fetching export runs...</p>
            </div>
        )
    }

    // If we have an error, show the error message.
    if (error) {
        return (
            <div>
                <h1>Export Runs</h1>
                <p>Error fetching export runs: {error}</p>
            </div>
        )
    }

    // I originally tried using only a Map here, but that was /too/ simple for the type checker.
    // Feel free to change this.
    const exportRunKeys = new Array<ExportRunKey>()
    const exportRunsMap = new Map<string, BatchExportRun[]>()
    exportRuns.forEach((run) => {
        const key = run.batch_export_id + dayjs(run.data_interval_end).format('YYYY-MM-DDTHH:MM:SSZ')
        const arr = exportRunsMap.get(key)

        if (!arr) {
            exportRunKeys.push({ workflow_id: key })
            exportRunsMap.set(key, [run])
        } else {
            arr.push(run)
        }
    })

    // If we have export runs, show the export runs in a table, showing:
    // - The export run status e.g. running, failed, etc.
    // - The export run start time.
    // - The export run end time.
    // - The export run duration.
    // - The export run size.
    return (
        <>
            <h1>Export Runs</h1>
            <div className="flex gap-2 mb-4">
                <Popover
                    actionable
                    onClickOutside={function noRefCheck() {
                        setDateRangeVisible(false)
                    }}
                    visible={dateRangeVisible}
                    overlay={
                        <LemonCalendarRange
                            value={dateRange}
                            onChange={(range) => {
                                setDateRange([startOfDay(range[0]), endOfDay(range[1])])
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
                    >
                        {dateRange[0].format('MMMM D, YYYY')} - {dateRange[1].format('MMMM D, YYYY')}
                    </LemonButton>
                </Popover>
                <LemonInput
                    type="number"
                    value={numberOfRuns}
                    disabled={loading}
                    onChange={(newValue) => {
                        setNumberOfRuns(newValue ? newValue : numberOfRuns)
                    }}
                />
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    disabled={loading}
                    onClick={() => {
                        updateCallback(undefined, numberOfRuns, dateRange).then(() => {
                            if (error === undefined) {
                                lemonToast['info'](<>Refreshed Export Runs</>, {
                                    toastId: `refreshed-export-runs-info`,
                                })
                            } else {
                                lemonToast['error'](<>Export Runs could not be refreshed: {error}</>, {
                                    toastId: `refreshed-export-runs-error`,
                                })
                            }
                        })
                    }}
                >
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                dataSource={exportRunKeys}
                defaultSorting={{ columnKey: 'created_at', order: -1 }}
                loading={loading}
                expandable={{
                    expandedRowRender: function renderExpand(exportRunKey) {
                        const runs = exportRunsMap.get(exportRunKey.workflow_id)

                        if (runs === undefined) {
                            // Each array will have at least one run (the original).
                            // So, we should never land here; I am only pleasing the type checker.
                            return (
                                <div>
                                    <p>Error fetching export runs</p>
                                </div>
                            )
                        }

                        return (
                            <LemonTable
                                dataSource={runs}
                                embedded={true}
                                size="small"
                                columns={[
                                    {
                                        title: 'Status',
                                        key: 'status',
                                        render: function RenderStatus(_, run) {
                                            return <ExportRunStatus exportRun={run} />
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
                                            return <>{dayjs(run.created_at).format('YYYY-MM-DD HH:mm:ss z')}</>
                                        },
                                    },
                                ]}
                            />
                        )
                    },
                }}
                columns={[
                    {
                        title: 'Last status',
                        key: 'lastStatus',
                        render: function RenderStatus(_, exportRunKey) {
                            const runs = exportRunsMap.get(exportRunKey.workflow_id)
                            if (runs === undefined || runs.length === 0) {
                                // Each array will have at least one run (the original).
                                // So, we should never land here; I am only pleasing the type checker.
                                return <>{null}</>
                            }
                            const exportRun = runs[0]

                            return <ExportRunStatus exportRun={exportRun} />
                        },
                    },
                    {
                        title: 'Last run start',
                        key: 'lastRunStart',
                        tooltip: 'Date and time when the last run for this batch started',
                        render: function RenderName(_, exportRunKey) {
                            const runs = exportRunsMap.get(exportRunKey.workflow_id)
                            if (runs === undefined || runs.length === 0) {
                                // Each array will have at least one run (the original).
                                // So, we should never land here; I am only pleasing the type checker.
                                return <>{null}</>
                            }
                            const exportRun = runs[0]

                            return <>{dayjs(exportRun.created_at).format('YYYY-MM-DD HH:mm:ss z')}</>
                        },
                    },
                    {
                        title: 'Data interval start',
                        key: 'dataIntervalStart',
                        tooltip: 'Start of the time range to export',
                        render: function RenderName(_, exportRunKey) {
                            const runs = exportRunsMap.get(exportRunKey.workflow_id)
                            if (runs === undefined || runs.length === 0) {
                                // Each array will have at least one run (the original).
                                // So, we should never land here; I am only pleasing the type checker.
                                return <>{null}</>
                            }
                            const exportRun = runs[0]

                            return <>{dayjs(exportRun.data_interval_start).format('YYYY-MM-DD HH:mm:ss z')}</>
                        },
                    },
                    {
                        title: 'Data interval end',
                        key: 'dataIntervalEnd',
                        tooltip: 'End of the time range to export',
                        render: function RenderName(_, exportRunKey) {
                            const runs = exportRunsMap.get(exportRunKey.workflow_id)
                            if (runs === undefined || runs.length === 0) {
                                // Each array will have at least one run (the original).
                                // So, we should never land here; I am only pleasing the type checker.
                                return <>{null}</>
                            }
                            const exportRun = runs[0]

                            return <>{dayjs(exportRun.data_interval_end).format('YYYY-MM-DD HH:mm:ss z')}</>
                        },
                    },
                    {
                        title: 'Actions',
                        render: function RenderName(_, exportRunKey) {
                            const runs = exportRunsMap.get(exportRunKey.workflow_id)
                            if (runs === undefined || runs.length === 0) {
                                // Each array will have at least one run (the original).
                                // So, we should never land here; I am only pleasing the type checker.
                                return <>{null}</>
                            }
                            const exportRun = runs.slice(-1)[0]

                            const {
                                executeExportRunAction: resetExportRun,
                                loading: restarting,
                                error: resetError,
                            } = useExportRunAction(currentTeamId, exportId, exportRun.id, 'reset')

                            return (
                                <div className={clsx('flex flex-wrap gap-2')}>
                                    <LemonButton
                                        status="primary"
                                        type="secondary"
                                        onClick={() => {
                                            resetExportRun()
                                                .then(() => {
                                                    updateCallback(undefined, numberOfRuns, dateRange)
                                                    lemonToast['success'](
                                                        <>
                                                            <b>{exportRun.id}</b> has been restarted
                                                        </>,
                                                        {
                                                            toastId: `restart-export-run-success-${exportRun.id}`,
                                                        }
                                                    )
                                                })
                                                .catch(() => {
                                                    lemonToast['error'](
                                                        <>
                                                            <b>{exportRun.id}</b> could not be restarted: {resetError}
                                                        </>,
                                                        {
                                                            toastId: `restart-export-run-error-${exportRun.id}`,
                                                        }
                                                    )
                                                })
                                        }}
                                        tooltip={'Restart this Batch Export run'}
                                        disabled={loading || restarting}
                                        icon={<IconReplay />}
                                    />
                                </div>
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
