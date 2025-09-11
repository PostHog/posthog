import clsx from 'clsx'

import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyMilliseconds } from 'lib/utils'

import { PerformanceEvent, RecordingEventType } from '~/types'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'

interface SummaryCardData {
    label: string
    description: JSX.Element
    scoreBenchmarks: number[]
    allowLoadingIndicator: boolean
}

const fcpSummary: SummaryCardData = {
    label: 'FCP',
    description: (
        <div>
            The First Contentful Paint (FCP) metric measures the time from when the page starts loading to when any part
            of the page's content is rendered on the screen.{' '}
            <Link
                disableClientSideRouting
                to="https://developer.mozilla.org/en-US/docs/Glossary/First_contentful_paint"
                target="_blank"
            >
                Read more on developer.mozilla.org
            </Link>
        </div>
    ),
    scoreBenchmarks: [1800, 3000],
    allowLoadingIndicator: true,
}

const domInteractiveSummary: SummaryCardData = {
    label: 'DOM Interactive',
    description: (
        <div>
            The document has finished loading and the document has been parsed but sub-resources such as scripts,
            images, stylesheets and frames are still loading.{' '}
            <Link
                disableClientSideRouting
                to="https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState"
                target="_blank"
            >
                Read more on developer.mozilla.org
            </Link>
        </div>
    ),
    scoreBenchmarks: [3800, 7300],
    allowLoadingIndicator: false,
}

const pageLoadedSummary: SummaryCardData = {
    label: 'Page Loaded',
    description: (
        <div>
            The load event is fired when the whole page has loaded, including all dependent resources such as
            stylesheets and images. This is in contrast to DOMContentLoaded, which is fired as soon as the page DOM has
            been loaded, without waiting for resources to finish loading.{' '}
            <Link
                disableClientSideRouting
                to="https://developer.mozilla.org/en-US/docs/Web/API/Window/load_event"
                target="_blank"
            >
                Read more on developer.mozilla.org
            </Link>
        </div>
    ),
    scoreBenchmarks: [3800, 7300],
    allowLoadingIndicator: false,
}

const clsSummary: SummaryCardData = {
    label: 'CLS',
    description: (
        <div>
            Cumulative layout shift (CLS) measures the extent to which users encounter unexpected layout shifts, in
            which elements of the page are moved in an unexpected way: that is, that are not the result of a user action
            like pressing a button or part of an animation.{' '}
            <Link disableClientSideRouting to="https://developer.mozilla.org/en-US/docs/Glossary/CLS" target="_blank">
                Read more on developer.mozilla.org
            </Link>
        </div>
    ),

    scoreBenchmarks: [0.1, 0.25],
    allowLoadingIndicator: true,
}

const lcpSummary: SummaryCardData = {
    label: 'LCP',
    description: (
        <div>
            The Largest Contentful Paint (LCP) performance metric provides the render time of the largest image or text
            block visible within the viewport, recorded from when the page first begins to load.{' '}
            <Link
                disableClientSideRouting
                to="https://developer.mozilla.org/en-US/docs/Glossary/Largest_contentful_paint"
                target="_blank"
            >
                Read more on developer.mozilla.org
            </Link>
        </div>
    ),

    scoreBenchmarks: [2500, 4000],
    allowLoadingIndicator: true,
}

const inpSummary: SummaryCardData = {
    label: 'INP',
    description: (
        <div>
            Interaction to next paint (INP) is a metric that assesses a page's overall responsiveness to user
            interactions by observing the latency of all click, tap, and keyboard interactions that occur throughout the
            lifespan of a user's visit to a page. The final INP value is the longest interaction observed, ignoring
            outliers.{' '}
            <Link disableClientSideRouting to="https://web.dev/articles/inp" target="_blank">
                Read more on web.dev
            </Link>
        </div>
    ),

    scoreBenchmarks: [200, 500],
    allowLoadingIndicator: true,
}

const summaryMapping = {
    domInteractive: domInteractiveSummary,
    fcp: fcpSummary,
    pageLoaded: pageLoadedSummary,
    lcp: lcpSummary,
    cls: clsSummary,
    inp: inpSummary,
}

export function PerformanceDuration({
    value,
    benchmarks,
    loading,
}: {
    benchmarks: number[]
    value: number | undefined
    loading?: boolean
}): JSX.Element {
    return value === undefined ? (
        <>-</>
    ) : (
        <span
            className={clsx({
                'text-error': !loading && value >= benchmarks[1],
                'text-warning': !loading && value >= benchmarks[0] && value < benchmarks[1],
                'text-success': !loading && value < benchmarks[0],
            })}
        >
            {loading ? <Spinner textColored={true} /> : humanFriendlyMilliseconds(value)}
        </span>
    )
}

function itemToPerformanceValues(item: PerformanceEvent): {
    cls?: number
    lcp?: number
    fcp?: number
    inp?: number
    domInteractive?: number
    pageLoaded?: number
    loaded: boolean
} {
    const webVitals: RecordingEventType[] = item.web_vitals ? Array.from(item.web_vitals) : []

    const clsEvent = webVitals.find((event) => event.properties.$web_vitals_CLS_value)
    const lcpEvent = webVitals.find((event) => event.properties.$web_vitals_LCP_value)
    const fcpEvent = webVitals.find((event) => event.properties.$web_vitals_FCP_value)
    const inpEvent = webVitals.find((event) => event.properties.$web_vitals_INP_value)

    return {
        cls: clsEvent?.properties.$web_vitals_CLS_value,
        lcp: lcpEvent?.properties.$web_vitals_LCP_value,
        fcp: item.first_contentful_paint || fcpEvent?.properties.$web_vitals_FCP_value,
        inp: inpEvent?.properties.$web_vitals_INP_value,
        domInteractive: item.dom_interactive,
        pageLoaded: item.load_event_end,
        loaded:
            (clsEvent === undefined || clsEvent.fullyLoaded) &&
            (lcpEvent === undefined || lcpEvent.fullyLoaded) &&
            (fcpEvent === undefined || fcpEvent.fullyLoaded) &&
            (inpEvent === undefined || inpEvent.fullyLoaded),
    }
}

export function PerformanceCardRow({ item }: { item: PerformanceEvent }): JSX.Element {
    const performanceValues = itemToPerformanceValues(item)
    return (
        <OverviewGrid>
            {Object.entries(summaryMapping)
                .filter(([key]) => performanceValues[key] !== undefined)
                .map(([key, summary]) => {
                    return (
                        <OverviewGridItem key={key} description={summary.description} label={summary.label}>
                            <PerformanceDuration
                                benchmarks={summary.scoreBenchmarks}
                                value={performanceValues[key]}
                                loading={summary.allowLoadingIndicator && !performanceValues.loaded}
                            />
                        </OverviewGridItem>
                    )
                })}
        </OverviewGrid>
    )
}

export function PerformanceCardDescriptions({
    item,
    expanded,
}: {
    item: PerformanceEvent
    expanded: boolean
}): JSX.Element {
    const performanceValues = itemToPerformanceValues(item)
    return (
        <div className={clsx('p-2 text-xs border-t', !expanded && 'hidden')}>
            {Object.entries(summaryMapping)
                .filter(([key]) => performanceValues[key] !== undefined)
                .map(([key, summary]) => (
                    <PerformanceCardDescription
                        key={key}
                        benchmarks={summary.scoreBenchmarks}
                        description={summary.description}
                        label={summary.label}
                        value={performanceValues[key]}
                    />
                ))}
        </div>
    )
}

function PerformanceCardDescription({
    label,
    benchmarks,
    value,
    description,
}: {
    benchmarks: number[]
    description: JSX.Element
    label: string
    value: number | undefined
}): JSX.Element {
    return (
        <>
            <div className="flex gap-2 font-semibold my-1">
                <span>{label}</span>
                <PerformanceDuration benchmarks={benchmarks} value={value} />
            </div>

            <p>{description}</p>
        </>
    )
}
