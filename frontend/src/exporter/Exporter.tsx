import '~/styles'
import './Exporter.scss'
import { useEffect } from 'react'
import { ExportedData, ExportType } from '~/exporter/types'
import { DashboardPlacement } from '~/types'
import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'
import { Logo } from '~/toolbar/assets/Logo'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { Link } from 'lib/lemon-ui/Link'
import clsx from 'clsx'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { exporterViewLogic } from './exporterViewLogic'

export function Exporter(props: ExportedData): JSX.Element {
    // NOTE: Mounting the logic is important as it is used by sub-logics
    const { exportedData } = useValues(exporterViewLogic(props))
    const { type, dashboard, insight, recording, accessToken, ...exportOptions } = exportedData
    const { whitelabel, showInspector = false } = exportOptions

    const { currentTeam } = useValues(teamLogic)
    const { ref: elementRef, height, width } = useResizeObserver()

    useEffect(() => {
        // NOTE: For embedded views we emit an event to indicate the content width / height to allow the parent to correctly resize
        // NOTE: We post the window name to allow the parent to identify the iframe
        window.parent?.postMessage({ event: 'posthog:dimensions', name: window.name, height, width }, '*')
    }, [height, width])

    return (
        <div
            className={clsx('Exporter', {
                'Exporter--insight': !!insight,
                'Exporter--dashboard': !!dashboard,
                'Exporter--recording': !!recording,
            })}
            ref={elementRef}
        >
            {!whitelabel && dashboard ? (
                type === ExportType.Scene ? (
                    <div className="SharedDashboard-header">
                        <Link
                            to="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard"
                            target="_blank"
                        >
                            <Logo className="text-lg" />
                        </Link>
                        <div className="SharedDashboard-header-title">
                            <h1 className="mb-2" data-attr="dashboard-item-title">
                                {dashboard.name}
                            </h1>
                            <span>{dashboard.description}</span>
                        </div>
                        <span className="SharedDashboard-header-team">{currentTeam?.name}</span>
                    </div>
                ) : type === ExportType.Embed ? (
                    <Link to="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard" target="_blank">
                        <Logo className="text-lg" />
                    </Link>
                ) : type === ExportType.Image ? (
                    <>
                        <h1 className="mb-2">{dashboard.name}</h1>
                        <p>{dashboard.description}</p>
                    </>
                ) : null
            ) : null}
            {insight ? (
                <ExportedInsight type={type} insight={insight} exportOptions={exportOptions} />
            ) : dashboard ? (
                <Dashboard
                    id={String(dashboard.id)}
                    dashboard={dashboard}
                    placement={type === ExportType.Image ? DashboardPlacement.Export : DashboardPlacement.Public}
                />
            ) : recording ? (
                <SessionRecordingPlayer
                    playerKey="exporter"
                    sessionRecordingId={recording.id}
                    mode={SessionRecordingPlayerMode.Sharing}
                    autoPlay={false}
                    noInspector={!showInspector}
                />
            ) : (
                <h1 className="text-center p-4">Something went wrong...</h1>
            )}
            {!whitelabel && dashboard && (
                <div className="text-center pb-4">
                    {type === ExportType.Image ? <Logo className="text-lg" /> : null}
                    <div>
                        Made with{' '}
                        <Link
                            to="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard"
                            target="_blank"
                        >
                            PostHog — open-source product analytics
                        </Link>
                    </div>
                </div>
            )}
        </div>
    )
}
