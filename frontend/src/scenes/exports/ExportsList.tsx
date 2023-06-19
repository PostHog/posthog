import { SceneExport } from 'scenes/sceneTypes'
import { urls } from '../urls'
import { LemonButton } from '../../lib/lemon-ui/LemonButton'
import { LemonTag } from '../../lib/lemon-ui/LemonTag/LemonTag'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { IconPlay, IconPause, IconDelete } from 'lib/lemon-ui/icons'
import { useCurrentTeamId, useExports, useExportAction, useDeleteExport, BatchExport } from './api'
import { LemonTable } from '../../lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import clsx from 'clsx'

export const scene: SceneExport = {
    component: Exports,
}

export interface ExportActionButtonsProps {
    currentTeamId: number
    export_: BatchExport
    loading: boolean
    updateCallback: (signal: AbortSignal | undefined) => void
}

export function ExportActionButtons({
    currentTeamId,
    export_,
    loading,
    updateCallback,
}: ExportActionButtonsProps): JSX.Element {
    const { executeExportAction: pauseExport, error: pauseError } = useExportAction(currentTeamId, export_.id, 'pause')
    const { executeExportAction: resumeExport, error: resumeError } = useExportAction(
        currentTeamId,
        export_.id,
        'unpause'
    )

    const { deleteExport, error: deleteError } = useDeleteExport(currentTeamId, export_.id)

    return (
        <div className={clsx('flex flex-wrap gap-2')}>
            <LemonButton
                status="primary"
                type="secondary"
                onClick={() => {
                    export_.paused
                        ? resumeExport()
                              .then(() => {
                                  updateCallback(undefined)
                                  lemonToast['success'](
                                      <>
                                          <b>{export_.name}</b> has been resumed
                                      </>,
                                      {
                                          toastId: `resume-export-success-${export_.id}`,
                                      }
                                  )
                              })
                              .catch(() => {
                                  lemonToast['error'](
                                      <>
                                          <b>{export_.name}</b> could not be resumed: {resumeError}
                                      </>,
                                      {
                                          toastId: `resume-export-error-${export_.id}`,
                                      }
                                  )
                              })
                        : pauseExport()
                              .then(() => {
                                  updateCallback(undefined)
                                  lemonToast['info'](
                                      <>
                                          <b>{export_.name}</b> has been paused
                                      </>,
                                      {
                                          toastId: `pause-export-info-${export_.id}`,
                                      }
                                  )
                              })
                              .catch(() => {
                                  lemonToast['error'](
                                      <>
                                          <b>{export_.name}</b> could not be resumed: {pauseError}
                                      </>,
                                      {
                                          toastId: `pause-export-error-${export_.id}`,
                                      }
                                  )
                              })
                }}
                icon={export_.paused ? <IconPlay /> : <IconPause />}
                tooltip={export_.paused ? 'Resume this BatchExport' : 'Pause this BatchExport'}
                disabled={loading}
                loading={loading}
            />
            <LemonButton
                status="danger"
                type="secondary"
                onClick={() => {
                    deleteExport()
                        .then(() => {
                            updateCallback(undefined)
                            lemonToast['success'](
                                <>
                                    <b>{export_.name}</b> has been deleted
                                </>,
                                {
                                    toastId: `delete-export-success-${export_.id}`,
                                }
                            )
                        })
                        .catch(() => {
                            lemonToast['error'](
                                <>
                                    <b>{export_.name}</b> could not be deleted: {deleteError}
                                </>,
                                {
                                    toastId: `delete-export-error-${export_.id}`,
                                }
                            )
                        })
                }}
                icon={<IconDelete />}
                tooltip="Permanently delete this BatchExport"
                disabled={loading}
                loading={loading}
            />
        </div>
    )
}

export function Exports(): JSX.Element {
    // Displays a list of exports for the current project. We use the
    // useCurrentTeamId hook to get the current team ID, and then use the
    // useExports hook to fetch the list of exports for that team.
    const { currentTeamId } = useCurrentTeamId()
    const { exportsState, updateCallback } = useExports(currentTeamId)
    const { loading, error, exports } = exportsState

    // If exports hasn't been set yet, we display a placeholder and a loading
    // spinner.
    if (exports === undefined) {
        return (
            <div>
                <h1>Exports</h1>
                <p>Fetching exports...</p>
            </div>
        )
    }

    // If we have an error, we display the error message.
    if (error) {
        return (
            <div>
                <h1>Exports</h1>
                <p>Error fetching exports: {error}</p>
            </div>
        )
    }

    // If we have exports we display them in a table, showing:
    // - The export type e.g. S3, Snowflake, etc.
    // - The export frequency e.g. hourly, daily, etc.
    // - The export status e.g. running, failed, etc.
    // - The export last run time.
    return (
        <>
            <h1>Exports</h1>
            <LemonTable
                dataSource={exports}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: function RenderName(_, export_) {
                            return <Link to={urls.viewExport(export_.id)}>{export_.name}</Link>
                        },
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: function RenderType(_, export_) {
                            return <>{export_.destination.type}</>
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: function RenderStatus(_, export_) {
                            return (
                                <>
                                    {export_.paused === true ? (
                                        <LemonTag type="default" className="uppercase">
                                            Paused
                                        </LemonTag>
                                    ) : (
                                        <LemonTag type="primary" className="uppercase">
                                            Running
                                        </LemonTag>
                                    )}
                                </>
                            )
                        },
                    },
                    {
                        title: 'Frequency',
                        key: 'frequency',
                        dataIndex: 'interval',
                    },
                    {
                        title: 'Actions',
                        render: function Render(_, export_) {
                            return (
                                <ExportActionButtons
                                    currentTeamId={currentTeamId}
                                    export_={export_}
                                    loading={loading}
                                    updateCallback={updateCallback}
                                />
                            )
                        },
                    },
                ]}
            />
            <LemonButton to={urls.createExport()}>Create export</LemonButton>
            {/* If we are loading, we overlay a spinner */}
            {loading && <div>Loading...</div>}
        </>
    )
}
