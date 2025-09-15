import { useValues } from 'kea'

import { LemonBanner, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    METRIC_DESCRIPTION,
    WEB_VITALS_THRESHOLDS,
    getThresholdColor,
    getValueWithUnit,
} from '~/queries/nodes/WebVitals/definitions'
import { WebVitalsMetric } from '~/queries/schema/schema-general'
import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'

import { toolbarConfigLogic } from '../toolbarConfigLogic'
import { WebVitalsMetrics, webVitalsToolbarLogic } from './webVitalsToolbarLogic'

// Same order as in the Web Vitals report
const ALL_METRICS: WebVitalsMetric[] = ['INP', 'LCP', 'FCP', 'CLS']

export const WebVitalsToolbarMenu = (): JSX.Element => {
    const { localWebVitals, remoteWebVitals } = useValues(webVitalsToolbarLogic)
    const { posthog, apiURL } = useValues(toolbarConfigLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Body>
                <div className="flex flex-col gap-2">
                    {!posthog?.webVitalsAutocapture?.isEnabled && !inStorybookTestRunner() && !inStorybook() && (
                        <LemonBanner type="warning">
                            Web vitals are not enabled for this project so you won't see any data here. Enable it on the{' '}
                            <Link to={urls.settings()}>settings page</Link> to start capturing web vitals.
                        </LemonBanner>
                    )}

                    <MetricCards
                        metrics={localWebVitals}
                        label={<span className="text-sm font-bold">Metrics for the current page load</span>}
                    />
                    <span className="text-sm mb-2">
                        <i>
                            Not all metrics are reported on every page load. INP/CLS won't be reported until you've
                            interacted enough with the page.
                        </i>
                    </span>

                    <MetricCards
                        metrics={remoteWebVitals}
                        label={
                            <span className="text-sm font-bold">
                                <DottedTooltip title="90% of all page loads have a performance better than this value">
                                    P90
                                </DottedTooltip>{' '}
                                metrics for{' '}
                                <DottedTooltip
                                    title={
                                        <span className="text-sm">
                                            <code>{window.location.pathname}</code> and all paths under the same result
                                            after path cleaning
                                        </span>
                                    }
                                >
                                    this path
                                </DottedTooltip>{' '}
                                in the last 7 days.
                            </span>
                        }
                    />
                </div>
            </ToolbarMenu.Body>

            <ToolbarMenu.Footer>
                <div className="flex flex-row justify-between w-full">
                    <Link to={`${apiURL}${urls.webAnalyticsWebVitals()}`} target="_blank">
                        View all metrics
                    </Link>
                    <Link to="https://posthog.com/docs/web-analytics/web-vitals" target="_blank">
                        View web vitals docs
                    </Link>
                </div>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}

const MetricCards = ({ metrics, label }: { metrics: WebVitalsMetrics; label: React.ReactNode }): JSX.Element => {
    return (
        <div>
            <span className="text-sm mb-1">{label}</span>
            <div className="flex flex-row gap-2">
                {ALL_METRICS.map((metric) => (
                    <MetricCard key={metric} metric={metric} value={metrics[metric]} />
                ))}
            </div>
        </div>
    )
}

const MetricCard = ({ metric, value }: { metric: WebVitalsMetric; value: number | null | undefined }): JSX.Element => {
    const { value: valueWithUnit, unit = '' } = getValueWithUnit(value ?? 0, metric)

    const color = getThresholdColor(value ?? 0, metric)

    const threshold = WEB_VITALS_THRESHOLDS[metric]
    const thresholdUnit = metric === 'CLS' ? '' : 'ms'

    return (
        <div className="border rounded-md p-2">
            <DottedTooltip
                title={
                    <p>
                        {METRIC_DESCRIPTION[metric]}
                        <br />
                        <div>
                            <strong>Great:</strong> Below {threshold.good}
                            {thresholdUnit} <br />
                            <strong>Needs Improvement:</strong> Between {threshold.good}
                            {thresholdUnit} and {threshold.poor}
                            {thresholdUnit} <br />
                            <strong>Poor:</strong> Above {threshold.poor}
                            {thresholdUnit}
                        </div>
                    </p>
                }
            >
                {metric}:
            </DottedTooltip>
            <span
                // eslint-disable-next-line react/forbid-dom-props
                style={{ color }}
                className="text-sm"
            >
                {' '}
                {value === undefined ? <WebVitalsToolbarSpinner /> : value === null ? 'N/A' : `${valueWithUnit}${unit}`}
            </span>
        </div>
    )
}

const DottedTooltip = ({ children, title }: { children: React.ReactNode; title: React.ReactNode }): JSX.Element => {
    return (
        <Tooltip title={<div className="text-sm min-w-80">{title}</div>} interactive>
            <span className="text-sm font-bold border-b border-dotted border-accent cursor-help">{children}</span>
        </Tooltip>
    )
}

const WebVitalsToolbarSpinner = (): JSX.Element => {
    // Avoid showing a spinner in Storybook Test Runner,
    // because tests won't ever finish waiting for them to disappear
    if (inStorybookTestRunner()) {
        return <></>
    }

    return <Spinner speed="2s" />
}
