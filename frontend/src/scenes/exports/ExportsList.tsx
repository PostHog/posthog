import { SceneExport } from 'scenes/sceneTypes'
import { urls } from '../urls'
import { LemonButton } from '../../lib/lemon-ui/LemonButton'
import { LemonTag } from '../../lib/lemon-ui/LemonTag/LemonTag'
import { IconPlay, IconPause } from 'lib/lemon-ui/icons'
import { useCurrentTeamId, useExports, useExportAction } from './api'
import { LemonTable } from '../../lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import clsx from 'clsx'

export const scene: SceneExport = {
    component: Exports,
}

export function Exports(): JSX.Element {
    // Displays a list of exports for the current project. We use the
    // useCurrentTeamId hook to get the current team ID, and then use the
    // useExports hook to fetch the list of exports for that team.
    const { currentTeamId } = useCurrentTeamId()
    const { loading, exports, error } = useExports(currentTeamId)

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
                            const {
                                executeExportAction: pauseExport,
                                loading: pausing,
                                error: pauseError,
                            } = useExportAction(currentTeamId, export_.id, 'pause')
                            const {
                                executeExportAction: resumeExport,
                                loading: resuming,
                                error: resumeError,
                            } = useExportAction(currentTeamId, export_.id, 'unpause')

                            return (
                                <div className={clsx('flex flex-wrap')}>
                                    <LemonButton
                                        status="primary"
                                        type="secondary"
                                        onClick={() => {
                                            export_.paused
                                                ? resumeExport().then(() => {
                                                      if (resumeError === null) {
                                                          export_.paused = false
                                                      }
                                                  })
                                                : pauseExport().then(() => {
                                                      if (pauseError === null) {
                                                          export_.paused = true
                                                      }
                                                  })
                                        }}
                                        icon={export_.paused ? <IconPlay /> : <IconPause />}
                                        tooltip={export_.paused ? 'Resume this BatchExport' : 'Pause this BatchExport'}
                                        loading={pausing || resuming}
                                    />
                                </div>
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
