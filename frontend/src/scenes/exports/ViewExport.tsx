import { useValues } from 'kea'
import { useCurrentTeamId, useExport, useExportRuns, BatchExport } from './api'
import { dayjs } from 'lib/dayjs'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ExportActionButtons } from './ExportsList'
import { LemonTable } from '../../lib/lemon-ui/LemonTable'
import { router } from 'kea-router'
import { useState } from 'react'

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
                <p>Fetching export...</p>
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
                    <ExportActionButtons
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

const ExportRuns = ({ exportId }: { exportId: string }): JSX.Element => {
    // Displays a list of export runs for the given export ID. We use the
    // useCurrentTeamId hook to get the current team ID, and then use the
    // useExportRuns hook to fetch the export runs for that team and export ID.
    const defaultNumberOfRuns = 25
    const [numberOfRuns, setNumberOfRuns] = useState<number>(defaultNumberOfRuns)
    const { currentTeamId } = useCurrentTeamId()
    const { loading, exportRuns, error, updateCallback } = useExportRuns(currentTeamId, exportId, defaultNumberOfRuns)
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
                        updateCallback(undefined, numberOfRuns).then(() => {
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
                dataSource={exportRuns}
                defaultSorting={{ columnKey: 'created_at', order: -1 }}
                loading={loading}
                columns={[
                    {
                        title: 'Status',
                        key: 'status',
                        render: function RenderStatus(_, exportRun) {
                            return (
                                <>
                                    {exportRun.status === 'Running' ? (
                                        <LemonTag type="primary" className="uppercase">
                                            Running
                                        </LemonTag>
                                    ) : exportRun.status === 'Completed' ? (
                                        <LemonTag type="success" className="uppercase">
                                            Completed
                                        </LemonTag>
                                    ) : (
                                        <LemonTag type="danger" className="uppercase">
                                            Error
                                        </LemonTag>
                                    )}
                                </>
                            )
                        },
                    },

                    {
                        title: 'Last run',
                        key: 'lastRun',
                        tooltip: 'Date and time when the last run for this batch started',
                        render: function RenderName(_, exportRun) {
                            return <>{dayjs(exportRun.created_at).format('YYYY-MM-DD HH:mm:ss z')}</>
                        },
                    },
                    {
                        title: 'Data interval start',
                        key: 'dataIntervalStart',
                        tooltip: 'Start of the time range to export',
                        render: function RenderName(_, exportRun) {
                            return <>{dayjs(exportRun.data_interval_start).format('YYYY-MM-DD HH:mm:ss z')}</>
                        },
                    },
                    {
                        title: 'Data interval end',
                        key: 'dataIntervalEnd',
                        tooltip: 'End of the time range to export',
                        render: function RenderName(_, exportRun) {
                            return <>{dayjs(exportRun.data_interval_end).format('YYYY-MM-DD HH:mm:ss z')}</>
                        },
                    },
                ]}
            />
        </>
    )
}
