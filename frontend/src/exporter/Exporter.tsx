import '~/styles'

import './Exporter.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { Logo } from 'lib/brand/Logo'
import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { Link } from 'lib/lemon-ui/Link'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'
import { ExporterLogin } from '~/exporter/ExporterLogin'
import { ExportType, ExportedData } from '~/exporter/types'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { DashboardPlacement } from '~/types'

import { exporterViewLogic } from './exporterViewLogic'

function ExportHeatmap(): JSX.Element {
    const { exportedData, isLoading, screenshotUrl } = useValues(exporterViewLogic)
    const { exportToken } = exportedData

    return (
        <div className="flex justify-center h-screen w-screen overflow-scroll heatmap-exporter relative">
            <HeatmapCanvas positioning="absolute" widthOverride={null} context="in-app" exportToken={exportToken} />
            {exportedData.heatmap_context?.heatmap_type === 'screenshot' ? (
                <>{isLoading ? null : <img src={screenshotUrl ?? ''} alt="Heatmap" />}</>
            ) : (
                <iframe
                    id="heatmap-iframe"
                    ref={null}
                    className="h-screen bg-white w-screen"
                    // eslint-disable-next-line react/forbid-dom-props
                    src={exportedData.heatmap_url ?? ''}
                    onLoad={() => {}}
                    // these two sandbox values are necessary so that the site and toolbar can run
                    // this is a very loose sandbox,
                    // but we specify it so that at least other capabilities are denied
                    sandbox="allow-scripts allow-same-origin"
                    // we don't allow things such as camera access though
                    allow=""
                />
            )}
        </div>
    )
}

export function Exporter(props: ExportedData): JSX.Element {
    // NOTE: Mounting the logic is important as it is used by sub-logics
    const { type, dashboard, insight, recording, themes, accessToken, exportToken, ...exportOptions } = props
    const { whitelabel, showInspector = false } = exportOptions

    const { currentTeam } = useValues(teamLogic)
    const { ref: elementRef, height, width } = useResizeObserver()

    useEffect(() => {
        // NOTE: For embedded views we emit an event to indicate the content width / height to allow the parent to correctly resize
        // NOTE: We post the window name to allow the parent to identify the iframe
        window.parent?.postMessage({ event: 'posthog:dimensions', name: window.name, height, width }, '*')
    }, [height, width])

    useThemedHtml(false)

    if (type === ExportType.Unlock) {
        return <ExporterLogin whitelabel={whitelabel} />
    }

    return (
        <BindLogic logic={exporterViewLogic} props={props}>
            <div
                className={clsx('Exporter', {
                    'Exporter--insight': !!insight,
                    'Exporter--dashboard': !!dashboard,
                    'Exporter--recording': !!recording,
                    'Exporter--heatmap': type === ExportType.Heatmap,
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
                        <Link
                            to="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard"
                            target="_blank"
                        >
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
                        mode={props.mode ?? SessionRecordingPlayerMode.Sharing}
                        autoPlay={props.autoplay ?? false}
                        noInspector={!showInspector}
                        noBorder={props.noBorder ?? false}
                        accessToken={exportToken}
                    />
                ) : type === ExportType.Heatmap ? (
                    <ExportHeatmap />
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
        </BindLogic>
    )
}
