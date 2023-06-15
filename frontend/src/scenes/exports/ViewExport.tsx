import { useValues } from 'kea'
import { useCurrentTeamId, useExport, useExportRuns, BatchExport } from './api'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ExportActionButtons } from './ExportsList'
import { router } from 'kea-router'

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
            <p>
                <strong>ID:</strong> {export_.id}
            </p>
            <p>
                <strong>Type:</strong> {export_.destination.type}
            </p>
            <p>
                <strong>Frequency:</strong> {export_.interval}
            </p>
            <p>
                <strong>Status:</strong> {export_.status}
            </p>

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
                        <div className="flex">
                            {export_.paused ? (
                                <LemonTag type="default" className="uppercase">
                                    Paused
                                </LemonTag>
                            ) : (
                                <LemonTag type="primary" className="uppercase">
                                    Running
                                </LemonTag>
                            )}
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
    const { currentTeamId } = useCurrentTeamId()
    const { loading, exportRuns, error } = useExportRuns(currentTeamId, exportId)

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
            <table>
                <thead>
                    <tr>
                        <th>Status</th>
                        <th>Start time</th>
                        <th>End time</th>
                    </tr>
                </thead>
                <tbody>
                    {exportRuns.map((exportRun) => (
                        <tr key={exportRun.id}>
                            <td>
                                {exportRun.status === 'Running' ? (
                                    <div className="running" />
                                ) : exportRun.status === 'Completed' ? (
                                    `✅`
                                ) : (
                                    `❌`
                                )}
                            </td>
                            <td>{exportRun.data_interval_start}</td>
                            <td>{exportRun.data_interval_end}</td>
                        </tr>
                    ))}
                </tbody>
            </table>

            {loading ? <p>Loading...</p> : null}
        </>
    )
}
