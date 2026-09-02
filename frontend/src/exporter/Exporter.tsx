import '~/styles'
import './Exporter.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { lazy, Suspense, useEffect } from 'react'

import { Logo } from 'lib/brand/Logo'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyDuration } from 'lib/utils'
import { AUTO_REFRESH_INITIAL_INTERVAL_SECONDS } from 'scenes/dashboard/dashboardConstants'
import { teamLogic } from 'scenes/teamLogic'

import { ExporterLogin } from '~/exporter/ExporterLogin'
import { ExportType, ExportedData } from '~/exporter/types'

import { exporterViewLogic } from './exporterViewLogic'

const LazyDashboardScene = lazy(() => import('./scenes/ExporterDashboardScene'))
const LazyNotebookScene = lazy(() => import('./scenes/ExporterNotebookScene'))
const LazyRecordingScene = lazy(() => import('./scenes/ExporterRecordingScene'))
const LazyHeatmapScene = lazy(() => import('./scenes/ExporterHeatmapScene'))
const LazyInsightScene = lazy(() => import('./scenes/ExporterInsightScene'))

function resolveForcedTheme(theme?: 'light' | 'dark' | 'system'): 'light' | 'dark' | null {
    if (theme === 'light' || theme === 'dark') {
        return theme
    }
    if (theme !== 'system') {
        return null
    }
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)')?.matches
        ? 'dark'
        : 'light'
}

export function Exporter(props: ExportedData): JSX.Element {
    const {
        type,
        dashboard,
        insight,
        recording,
        notebook,
        insights,
        inline_query_results: inlineQueryResults,
        themes,
        accessToken,
        exportToken,
        ...exportOptions
    } = props
    const { whitelabel, showInspector = false } = exportOptions
    const forcedTheme = resolveForcedTheme(exportOptions.theme)

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
        } else if (notebook && (type === ExportType.Scene || type === ExportType.Embed)) {
            const baseTitle = notebook.title || 'Notebook'
            document.title = whitelabel ? baseTitle : `${baseTitle} • PostHog`
        }
    }, [dashboard, insight, notebook, type, whitelabel])

    useThemedHtml(false, forcedTheme)

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
                    'Exporter--notebook': !!notebook,
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
                {notebook ? (
                    <div className="SharedNotebook">
                        {!whitelabel && type === ExportType.Scene && (
                            <div className="SharedDashboard-header">
                                <Link
                                    to="https://posthog.com?utm_medium=in-product&utm_campaign=shared-notebook"
                                    target="_blank"
                                >
                                    <Logo className="text-lg" />
                                </Link>
                                <div className="SharedDashboard-header-team text-right">
                                    <span className="block">{currentTeam?.name}</span>
                                </div>
                            </div>
                        )}
                        <Suspense fallback={null}>
                            <LazyNotebookScene
                                notebook={notebook}
                                insights={insights}
                                inline_query_results={inlineQueryResults}
                            />
                        </Suspense>
                    </div>
                ) : insight ? (
                    <Suspense fallback={null}>
                        <LazyInsightScene insight={insight} themes={themes!} exportOptions={exportOptions} />
                    </Suspense>
                ) : dashboard ? (
                    <Suspense fallback={null}>
                        <LazyDashboardScene dashboard={dashboard} type={type} themes={themes} />
                    </Suspense>
                ) : recording ? (
                    <Suspense fallback={null}>
                        <LazyRecordingScene
                            recording={recording}
                            mode={props.mode}
                            autoplay={props.autoplay}
                            noBorder={props.noBorder}
                            exportToken={exportToken}
                            showInspector={showInspector}
                        />
                    </Suspense>
                ) : type === ExportType.Heatmap ? (
                    <Suspense fallback={null}>
                        <LazyHeatmapScene />
                    </Suspense>
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
