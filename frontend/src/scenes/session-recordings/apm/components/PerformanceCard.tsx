import clsx from 'clsx'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyMilliseconds } from 'lib/utils'

import { PerformanceEvent, RecordingEventType } from '~/types'

interface SummaryCardData {
    label: string
    description: JSX.Element
    scoreBenchmarks: number[]
}

const fcpSummary: SummaryCardData = {
    label: 'First Contentful Paint',
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
}

const clsSummary: SummaryCardData = {
    label: 'Cumulative layout shift',
    description: (
        <div>
            Cumulative layout shift measures the extent to which users encounter unexpected layout shifts, in which
            elements of the page are moved in an unexpected way: that is, that are not the result of a user action like
            pressing a button or part of an animation.{' '}
            <Link disableClientSideRouting to="https://developer.mozilla.org/en-US/docs/Glossary/CLS" target="_blank">
                Read more on developer.mozilla.org
            </Link>
        </div>
    ),

    scoreBenchmarks: [0.1, 0.25],
}

const lcpSummary: SummaryCardData = {
    label: 'Largest Contentful Paint',
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
}

const inpSummary: SummaryCardData = {
    label: 'Interaction to next paint',
    description: (
        <div>
            INP is a metric that assesses a page's overall responsiveness to user interactions by observing the latency
            of all click, tap, and keyboard interactions that occur throughout the lifespan of a user's visit to a page.
            The final INP value is the longest interaction observed, ignoring outliers.{' '}
            <Link disableClientSideRouting to="https://web.dev/articles/inp" target="_blank">
                Read more on web.dev
            </Link>
        </div>
    ),

    scoreBenchmarks: [200, 500],
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
}: {
    benchmarks: number[]
    value: number | undefined
}): JSX.Element {
    return value === undefined ? (
        <>-</>
    ) : (
        <span
            className={clsx({
                'text-danger-dark': value >= benchmarks[1],
                'text-warning-dark': value >= benchmarks[0] && value < benchmarks[1],
                'text-success-dark': value < benchmarks[0],
            })}
        >
            {humanFriendlyMilliseconds(value)}
        </span>
    )
}

function PerformanceCard(props: {
    benchmarks: number[]
    description: JSX.Element
    label: string
    value: number | undefined
}): JSX.Element {
    return (
        <Tooltip title={props.description}>
            <div className="flex-1 p-2 text-center">
                <div className="text-sm">{props.label}</div>
                <div className="text-lg font-semibold">
                    <PerformanceDuration {...props} />
                </div>
            </div>
        </Tooltip>
    )
}

function itemToPerformanceValues(item: PerformanceEvent): {
    cls?: number
    lcp?: number
    fcp?: number
    inp?: number
    domInteractive?: number
    pageLoaded?: number
} {
    const webVitals: RecordingEventType[] = item.web_vitals ? Array.from(item.web_vitals) : []
    const clsValue = webVitals.find((event) => event.properties.$web_vitals_CLS_value)?.properties.$web_vitals_CLS_value
    const lcpValue = webVitals.find((event) => event.properties.$web_vitals_LCP_value)?.properties.$web_vitals_LCP_value
    const fcpValue =
        item.first_contentful_paint ||
        webVitals.find((event) => event.properties.$web_vitals_FCP_value)?.properties.$web_vitals_FCP_value
    const inpValue = webVitals.find((event) => event.properties.$web_vitals_INP_value)?.properties.$web_vitals_INP_value
    return {
        cls: clsValue,
        lcp: lcpValue,
        fcp: fcpValue,
        inp: inpValue,
        domInteractive: item.dom_interactive,
        pageLoaded: item.load_event_end,
    }
}

export function PerformanceCardRow({ item }: { item: PerformanceEvent }): JSX.Element {
    const performanceValues = itemToPerformanceValues(item)
    return (
        <div className="grid grid-cols-3 place-items-center">
            {Object.entries(summaryMapping).map(([key, summary]) => (
                <PerformanceCard
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
            {Object.entries(summaryMapping).map(([key, summary]) => (
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
