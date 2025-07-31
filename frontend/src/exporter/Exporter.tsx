import '~/styles'
import './Exporter.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { Link } from 'lib/lemon-ui/Link'
import { useEffect } from 'react'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'
import { ExportedData, ExportType } from '~/exporter/types'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { Logo } from '~/toolbar/assets/Logo'
import { DashboardPlacement } from '~/types'

import { exporterViewLogic } from './exporterViewLogic'

export function Exporter(props: ExportedData): JSX.Element {
    // NOTE: Mounting the logic is important as it is used by sub-logics
    const { exportedData } = useValues(exporterViewLogic(props))
    const { type, dashboard, insight, recording, themes, accessToken, ...exportOptions } = exportedData
    const { whitelabel, showInspector = false } = exportOptions

    const { currentTeam } = useValues(teamLogic)
    const { ref: elementRef, height, width } = useResizeObserver()

    useEffect(() => {
        // NOTE: For embedded views we emit an event to indicate the content width / height to allow the parent to correctly resize
        // NOTE: We post the window name to allow the parent to identify the iframe
        window.parent?.postMessage({ event: 'posthog:dimensions', name: window.name, height, width }, '*')
    }, [height, width])

    useThemedHtml(false)

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
                <ExportedInsight insight={insight} themes={themes!} exportOptions={exportOptions} />
            ) : dashboard ? (
                <Dashboard
                    id={String(dashboard.id)}
                    dashboard={getQueryBasedDashboard(dashboard)!}
                    placement={type === ExportType.Image ? DashboardPlacement.Export : DashboardPlacement.Public}
                    themes={themes}
                />
            ) : recording ? (
                <SessionRecordingPlayer
                    playerKey="exporter"
                    sessionRecordingId={recording.id}
                    mode={SessionRecordingPlayerMode.Sharing}
                    autoPlay={true}
                    noInspector={!showInspector}
                    noBorder={exportedData.noBorder ? exportedData.noBorder : false}
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
