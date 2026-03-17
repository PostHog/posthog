import '~/styles'
import './Exporter.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { Logo } from 'lib/brand/Logo'
import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyDuration } from 'lib/utils'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ExportedInsight } from '~/exporter/ExportedInsight/ExportedInsight'
import { ExporterLogin } from '~/exporter/ExporterLogin'
import { ExportType, ExportedData } from '~/exporter/types'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { AUTO_REFRESH_INITIAL_INTERVAL_SECONDS } from '~/scenes/dashboard/dashboardUtils'
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
                    title="Heatmap export"
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

function SharedDashboardAutoRefresh({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const { setAutoRefresh, setPageVisibility } = dashboardLogic({
        id: dashboardId,
        placement: DashboardPlacement.Public,
    }).actions

    // Tie dashboard auto-refresh to tab visibility, same as in-app dashboard.
    usePageVisibilityCb(setPageVisibility)

    useEffect(() => {
        setAutoRefresh(true, AUTO_REFRESH_INITIAL_INTERVAL_SECONDS)
    }, [setAutoRefresh])

    return null
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
        // it's ok to use we use a wildcard for the origin bc data isn't sensitive
        // nosemgrep: javascript.browser.security.wildcard-postmessage-configuration.wildcard-postmessage-configuration
        window.parent?.postMessage({ event: 'posthog:dimensions', name: window.name, height, width }, '*')
    }, [height, width])

    useEffect(() => {
        if (dashboard && (type === ExportType.Scene || type === ExportType.Embed)) {
            const baseTitle = dashboard.name || 'Dashboard'
            document.title = whitelabel ? baseTitle : `${baseTitle} • PostHog`
        } else if (insight && (type === ExportType.Scene || type === ExportType.Embed)) {
            const baseTitle = insight.name || insight.derived_name || 'Insight'
            document.title = whitelabel ? baseTitle : `${baseTitle} • PostHog`
        }
    }, [dashboard, insight, type, whitelabel])

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
                {dashboard ? (
                    type === ExportType.Scene ? (
                        <div className="SharedDashboard-header">
                            {!whitelabel && (
                                <Link
                                    to="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard"
                                    target="_blank"
                                >
                                    <Logo className="text-lg" />
                                </Link>
                            )}
                            <div className="SharedDashboard-header-title">
                                <h1 className="mb-2" data-attr="dashboard-item-title">
                                    {dashboard.name}
                                </h1>
                                <LemonMarkdown lowKeyHeadings>{dashboard.description || ''}</LemonMarkdown>
                            </div>
                            <div className="SharedDashboard-header-team text-right">
                                <span className="block">{currentTeam?.name}</span>
                                <span className="block text-xs text-muted-alt">
                                    Auto refresh every {humanFriendlyDuration(AUTO_REFRESH_INITIAL_INTERVAL_SECONDS)}
                                </span>
                            </div>
                        </div>
                    ) : type === ExportType.Embed && !whitelabel ? (
                        <Link
                            to="https://posthog.com?utm_medium=in-product&utm_campaign=shared-dashboard"
                            target="_blank"
                        >
                            <Logo className="text-lg" />
                        </Link>
                    ) : type === ExportType.Image && !whitelabel ? (
                        <>
                            <h1 className="mb-2">{dashboard.name}</h1>
                            <LemonMarkdown lowKeyHeadings>{dashboard.description || ''}</LemonMarkdown>
                        </>
                    ) : null
                ) : null}
                {insight ? (
                    <ExportedInsight insight={insight} themes={themes!} exportOptions={exportOptions} />
                ) : dashboard ? (
                    <>
                        {type !== ExportType.Image && <SharedDashboardAutoRefresh dashboardId={dashboard.id} />}
                        <Dashboard
                            id={String(dashboard.id)}
                            dashboard={getQueryBasedDashboard(dashboard)!}
                            placement={
                                type === ExportType.Image ? DashboardPlacement.Export : DashboardPlacement.Public
                            }
                            themes={themes}
                        />
                    </>
                ) : recording ? (
                    <SessionRecordingPlayer
                        playerKey="exporter"
                        sessionRecordingId={recording.id}
                        mode={props.mode ?? SessionRecordingPlayerMode.Sharing}
                        autoPlay={props.autoplay ?? false}
                        withSidebar={showInspector}
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
