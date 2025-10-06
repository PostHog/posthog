import './EmptyStates.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import {
    IconArchive,
    IconHourglass,
    IconInfo,
    IconPieChart,
    IconPlus,
    IconPlusSmall,
    IconPlusSquare,
    IconWarning,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { BuilderHog3 } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Link } from 'lib/lemon-ui/Link'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconErrorOutline, IconOpenInNew } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber, humanizeBytes, inStorybook, inStorybookTestRunner } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelsQuery, Node, QueryStatus } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    FilterType,
    InsightLogicProps,
    SavedInsightsTabs,
} from '~/types'

import { samplingFilterLogic } from '../EditorFilters/samplingFilterLogic'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightDataLogic } from '../insightDataLogic'
import { insightVizDataLogic } from '../insightVizDataLogic'

export function InsightEmptyState({
    heading = 'There are no matching events for this query',
    detail = 'Try changing the date range, or pick another action, event or breakdown.',
}: {
    heading?: string
    detail?: string | JSX.Element
}): JSX.Element {
    return (
        <div
            data-attr="insight-empty-state"
            className="flex flex-col flex-1 rounded p-4 w-full items-center justify-center text-center text-balance"
        >
            <IconArchive className="text-5xl mb-2 text-tertiary" />
            <h2 className="text-xl leading-tight">{heading}</h2>
            <p className="text-sm text-tertiary">{detail}</p>
        </div>
    )
}

function SamplingLink({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { setSamplingPercentage } = useActions(samplingFilterLogic(insightProps))
    const { suggestedSamplingPercentage } = useValues(samplingFilterLogic(insightProps))

    return (
        <Tooltip
            title={`Calculate results from ${suggestedSamplingPercentage}% of the total dataset for this insight, speeding up the calculation of results.`}
            placement="bottom"
        >
            <Link
                className="font-medium"
                onClick={() => {
                    setSamplingPercentage(suggestedSamplingPercentage)
                    posthog.capture('sampling_enabled_on_slow_query', {
                        samplingPercentage: suggestedSamplingPercentage,
                    })
                }}
            >
                <IconPieChart className="mt-1" /> {suggestedSamplingPercentage}% sampling
            </Link>
        </Tooltip>
    )
}

function QueryIdDisplay({ queryId }: { queryId?: string | null }): JSX.Element | null {
    if (queryId == null) {
        return null
    }

    return (
        <div className="text-muted text-xs">
            Query ID: <span className="font-mono">{queryId}</span>
        </div>
    )
}

function QueryDebuggerButton({ query }: { query?: Record<string, any> | null }): JSX.Element | null {
    if (!query) {
        return null
    }

    return (
        <LemonButton
            data-attr="insight-error-query"
            targetBlank
            size="small"
            type="secondary"
            active
            to={urls.debugQuery(query)}
            className="max-w-80"
        >
            Open in query debugger
        </LemonButton>
    )
}

const RetryButton = ({
    onRetry,
    query,
}: {
    onRetry: () => void
    query?: Record<string, any> | Node | null
}): JSX.Element => {
    let sideAction = {}
    if (query) {
        sideAction = {
            dropdown: {
                overlay: (
                    <LemonMenuOverlay
                        items={[
                            {
                                label: 'Open in query debugger',
                                to: urls.debugQuery(query),
                            },
                        ]}
                    />
                ),
                placement: 'bottom-end',
            },
        }
    }

    return (
        <LemonButton
            data-attr="insight-retry-button"
            size="small"
            type="primary"
            onClick={() => onRetry()}
            sideAction={sideAction}
        >
            Try again
        </LemonButton>
    )
}

export const LOADING_MESSAGES = [
    'Crunching through hogloads of data…',
    'Teaching hedgehogs to count…',
    'Waking up the hibernating data hogs…',
    'Polishing graphs with tiny hedgehog paws…',
    'Rolling through data like a spiky ball of insights…',
    'Gathering nuts and numbers from the data forest…',
    // eslint-disable-next-line react/jsx-key
    <>
        Reticulating <s>splines</s> spines…
    </>,
]

export const DELAYED_LOADING_MESSAGE = 'Waiting for changes...'

function LoadingDetails({
    pollResponse,
    queryId,
    rowsRead,
    bytesRead,
    secondsElapsed,
}: {
    pollResponse?: Record<string, QueryStatus | null> | null
    queryId?: string | null
    rowsRead: number
    bytesRead: number
    secondsElapsed: number
}): JSX.Element {
    const bytesPerSecond = (bytesRead / (secondsElapsed || 1)) * 1000
    const estimatedRows = pollResponse?.status?.query_progress?.estimated_rows_total
    const cpuUtilization =
        (pollResponse?.status?.query_progress?.active_cpu_time || 0) /
        (pollResponse?.status?.query_progress?.time_elapsed || 1) /
        10000

    return (
        <>
            <p className="mx-auto text-center text-xs">
                {rowsRead > 0 && bytesRead > 0 && (
                    <>
                        <span>{humanFriendlyNumber(rowsRead || 0, 0)} </span>
                        <span>
                            {estimatedRows && estimatedRows >= rowsRead ? (
                                <span>/ {humanFriendlyNumber(estimatedRows)} </span>
                            ) : null}
                        </span>
                        <span>rows</span>
                        <br />
                        <span>{humanizeBytes(bytesRead || 0)} </span>
                        <span>({humanizeBytes(bytesPerSecond || 0)}/s)</span>
                        <br />
                        <span>CPU {humanFriendlyNumber(cpuUtilization, 0)}%</span>
                    </>
                )}
            </p>
            <QueryIdDisplay queryId={queryId} />
        </>
    )
}

const LOADING_ANIMATION_DELAY_SECONDS = 4

export function StatelessInsightLoadingState({
    queryId,
    pollResponse,
    suggestion,
    setProgress,
    progress,
    delayLoadingAnimation = false,
    loadingTimeSeconds = 0,
    renderEmptyStateAsSkeleton = false,
}: {
    queryId?: string | null
    pollResponse?: Record<string, QueryStatus | null> | null
    suggestion?: JSX.Element
    delayLoadingAnimation?: boolean
    loadingTimeSeconds?: number
    renderEmptyStateAsSkeleton?: boolean
    setProgress?: (loadId: string, progress: number) => void
    progress?: number
}): JSX.Element {
    const [rowsRead, setRowsRead] = useState(0)
    const [bytesRead, setBytesRead] = useState(0)
    const [secondsElapsed, setSecondsElapsed] = useState(0)

    const [loadingMessageIndex, setLoadingMessageIndex] = useState(() =>
        inStorybook() || inStorybookTestRunner() ? 0 : Math.floor(Math.random() * LOADING_MESSAGES.length)
    )
    const [isLoadingMessageVisible, setIsLoadingMessageVisible] = useState(true)

    const showLoadingDetails = !delayLoadingAnimation || loadingTimeSeconds >= LOADING_ANIMATION_DELAY_SECONDS

    useEffect(() => {
        if (showLoadingDetails) {
            const status = pollResponse?.status?.query_progress
            const previousStatus = pollResponse?.previousStatus?.query_progress
            setRowsRead(previousStatus?.rows_read || 0)
            setBytesRead(previousStatus?.bytes_read || 0)

            const interval = setInterval(() => {
                setRowsRead((rowsRead) => {
                    const diff = (status?.rows_read || 0) - (previousStatus?.rows_read || 0)
                    return Math.min(rowsRead + diff / 30, status?.rows_read || 0)
                })
                setBytesRead((bytesRead) => {
                    const diff = (status?.bytes_read || 0) - (previousStatus?.bytes_read || 0)
                    return Math.min(bytesRead + diff / 30, status?.bytes_read || 0)
                })
                setSecondsElapsed(() => {
                    return dayjs().diff(dayjs(pollResponse?.status?.start_time), 'milliseconds')
                })
            }, 100)

            return () => clearInterval(interval)
        }
    }, [pollResponse, showLoadingDetails])

    // Toggle between loading messages every 2.5-3.5 seconds, with 300ms fade out, then change text, keep in sync with the transition duration below
    useOnMountEffect(() => {
        const TOGGLE_INTERVAL_MIN = 2500
        const TOGGLE_INTERVAL_JITTER = 1000
        const FADE_OUT_DURATION = 300

        // Don't toggle loading messages in storybook, will make tests flaky if so
        if (inStorybook() || inStorybookTestRunner()) {
            return
        }

        const interval = setInterval(
            () => {
                setIsLoadingMessageVisible(false)
                setTimeout(() => {
                    setLoadingMessageIndex((current) => {
                        // Attempt to do random messages, but don't do the same message twice
                        let newIndex = Math.floor(Math.random() * LOADING_MESSAGES.length)
                        if (newIndex === current) {
                            newIndex = (newIndex + 1) % LOADING_MESSAGES.length
                        }
                        return newIndex
                    })
                    setIsLoadingMessageVisible(true)
                }, FADE_OUT_DURATION)
            },
            TOGGLE_INTERVAL_MIN + Math.random() * TOGGLE_INTERVAL_JITTER
        )

        return () => clearInterval(interval)
    })

    const suggestions = suggestion ? (
        suggestion
    ) : showLoadingDetails ? (
        <div className="flex gap-3">
            <p className="text-xs m-0">Need to speed things up? Try reducing the date range.</p>
        </div>
    ) : null

    return (
        <div
            data-attr="insight-empty-state"
            className={clsx('flex flex-col gap-1 rounded p-4 w-full h-full', {
                'justify-center items-center': !renderEmptyStateAsSkeleton,
                'insights-loading-state justify-start': renderEmptyStateAsSkeleton,
            })}
        >
            <span
                className={clsx(
                    'font-semibold transition-opacity duration-300 mb-1',
                    renderEmptyStateAsSkeleton ? 'text-start' : 'text-center',
                    isLoadingMessageVisible ? 'opacity-100' : 'opacity-0'
                )}
            >
                {!showLoadingDetails ? (
                    <>
                        <IconHourglass className="mr-2 inline-block brief-spin" />
                        {DELAYED_LOADING_MESSAGE}
                    </>
                ) : (
                    LOADING_MESSAGES[loadingMessageIndex]
                )}
            </span>

            {showLoadingDetails && (
                <div
                    className={clsx(
                        'flex flex-col gap-2 justify-center max-w-120',
                        renderEmptyStateAsSkeleton ? 'items-start' : 'items-center'
                    )}
                >
                    <LoadingBar loadId={queryId} progress={progress} setProgress={setProgress} />
                    {suggestions}
                    <LoadingDetails
                        pollResponse={pollResponse}
                        queryId={queryId}
                        rowsRead={rowsRead}
                        bytesRead={bytesRead}
                        secondsElapsed={secondsElapsed}
                    />
                </div>
            )}
        </div>
    )
}

const CodeWrapper = (props: { children: React.ReactNode }): JSX.Element => (
    <code className="border border-1 border-primary rounded-xs text-xs px-1 py-0.5">{props.children}</code>
)

const SLOW_LOADING_TIME = 15
const EVEN_SLOWER_LOADING_TIME = 25

export function SlowQuerySuggestions({
    insightProps,
    suggestedSamplingPercentage,
    samplingPercentage,
    loadingTimeSeconds = 0,
}: {
    insightProps: InsightLogicProps
    suggestedSamplingPercentage?: number | null
    samplingPercentage?: number | null
    loadingTimeSeconds?: number
}): JSX.Element | null {
    const { slowQueryPossibilities } = useValues(insightVizDataLogic(insightProps))

    if (loadingTimeSeconds < SLOW_LOADING_TIME) {
        return null
    }

    const steps = [
        slowQueryPossibilities.includes('all_events') ? (
            <li key="all_events">
                Don't use the <CodeWrapper>All events</CodeWrapper> event type. Use a specific event instead.
            </li>
        ) : null,
        slowQueryPossibilities.includes('first_time_for_user') ? (
            <li key="first_time_for_user">
                When possible, avoid <CodeWrapper>First-ever occurrence</CodeWrapper> metric types.
            </li>
        ) : null,
        slowQueryPossibilities.includes('strict_funnel') ? (
            <li key="strict_funnel">
                When possible, use <CodeWrapper>Sequential</CodeWrapper> step order rather than{' '}
                <CodeWrapper>Strict</CodeWrapper>.
            </li>
        ) : null,
        <li key="reduce_date_range">Reduce the date range.</li>,
        loadingTimeSeconds >= EVEN_SLOWER_LOADING_TIME && suggestedSamplingPercentage ? (
            <li key="sampling">
                {samplingPercentage ? (
                    <>
                        Reduce volume further with <SamplingLink insightProps={insightProps} />.
                    </>
                ) : (
                    <>
                        Turn on <SamplingLink insightProps={insightProps} />.
                    </>
                )}
            </li>
        ) : null,
    ].filter((x) => x !== null)

    if (steps.length === 0) {
        return null
    }

    return (
        <div className="flex items-center p-4 rounded bg-primary gap-x-3">
            <IconInfo className="text-xl shrink-0" />
            <div className="text-xs">
                <p data-attr="insight-loading-waiting-message" className="m-0 mb-1">
                    Need to speed things up? Some steps to optimize this query:
                </p>
                <ul className="mb-0 list-disc list-inside ml-2">{steps}</ul>
            </div>
        </div>
    )
}

export function InsightLoadingState({
    queryId,
    insightProps,
    renderEmptyStateAsSkeleton = false,
}: {
    queryId?: string | null
    insightProps: InsightLogicProps
    renderEmptyStateAsSkeleton?: boolean
}): JSX.Element {
    const { suggestedSamplingPercentage, samplingPercentage } = useValues(samplingFilterLogic(insightProps))
    const { insightPollResponse, insightLoadingTimeSeconds, queryChanged } = useValues(insightDataLogic(insightProps))
    const { activeSceneId } = useValues(sceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const personsOnEventsMode =
        currentTeam?.modifiers?.personsOnEventsMode ?? currentTeam?.default_modifiers?.personsOnEventsMode ?? 'disabled'

    return (
        <StatelessInsightLoadingState
            queryId={queryId}
            pollResponse={insightPollResponse}
            delayLoadingAnimation={
                featureFlags[FEATURE_FLAGS.DELAYED_LOADING_ANIMATION] === 'test' &&
                activeSceneId == Scene.Insight &&
                queryChanged
            }
            loadingTimeSeconds={insightLoadingTimeSeconds}
            renderEmptyStateAsSkeleton={renderEmptyStateAsSkeleton}
            suggestion={
                personsOnEventsMode === 'person_id_override_properties_joined' ? (
                    <div className="text-xs">
                        You can speed this query up by changing the{' '}
                        <Link to="/settings/project#persons-on-events">person properties mode</Link> setting.
                    </div>
                ) : (
                    <SlowQuerySuggestions
                        insightProps={insightProps}
                        suggestedSamplingPercentage={suggestedSamplingPercentage}
                        samplingPercentage={samplingPercentage}
                        loadingTimeSeconds={insightLoadingTimeSeconds}
                    />
                )
            }
        />
    )
}

export function InsightTimeoutState({ queryId }: { queryId?: string | null }): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    return (
        <div data-attr="insight-empty-state" className="rounded p-4 h-full w-full">
            <h2 className="text-xl leading-tight mb-6 text-center text-balance">
                <IconWarning className="text-xl shrink-0 mr-2" />
                Your query took too long to complete
            </h2>

            <div className="rounded max-w-120 text-xs">
                Sometimes this happens. Try refreshing the page, reducing the date range, or removing breakdowns. If
                you're still having issues,{' '}
                <Link
                    onClick={() => {
                        openSupportForm({ kind: 'bug', target_area: 'analytics' })
                    }}
                >
                    let us know
                </Link>
                .
            </div>

            <QueryIdDisplay queryId={queryId} />
        </div>
    )
}

export function InsightValidationError({
    detail,
    query,
}: {
    detail: string
    query?: Record<string, any> | null
}): JSX.Element {
    return (
        <div
            data-attr="insight-empty-state"
            className="flex flex-col items-center justify-center gap-2 rounded p-4 h-full w-full text-center text-balance"
        >
            <IconWarning className="text-4xl shrink-0 text-muted" />

            <h2
                data-attr="insight-loading-too-long"
                className="text-xl font-bold leading-tight"
                // TODO: Use an actual `text-warning` color once @adamleithp changes are live
                // eslint-disable-next-line react/forbid-dom-props
                style={{ color: 'var(--warning)' }}
            >
                There is a problem with this query
                {/* Note that this phrasing above signals the issue is not intermittent, */}
                {/* but rather that it's something with the definition of the query itself */}
            </h2>

            <p className="text-sm text-muted max-w-120">{detail}</p>
            <QueryDebuggerButton query={query} />

            {detail.includes('Exclusion') && (
                <div className="mt-4">
                    <Link
                        data-attr="insight-funnels-emptystate-help"
                        to="https://posthog.com/docs/user-guides/funnels?utm_medium=in-product&utm_campaign=funnel-exclusion-filter-state"
                        target="_blank"
                    >
                        Learn more about funnels in PostHog docs
                        <IconOpenInNew style={{ marginLeft: 4, fontSize: '0.85em' }} />
                    </Link>
                </div>
            )}
        </div>
    )
}

export interface InsightErrorStateProps {
    title?: string | null
    query?: Record<string, any> | Node | null
    queryId?: string | null
    excludeDetail?: boolean
    excludeActions?: boolean
    fixWithAIComponent?: JSX.Element
    onRetry?: () => void
}

export function InsightErrorState({
    title,
    query,
    queryId,
    excludeDetail = false,
    excludeActions = false,
    fixWithAIComponent,
    onRetry,
}: InsightErrorStateProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    if (!preflight?.cloud) {
        excludeDetail = true // We don't provide support for self-hosted instances
    }

    return (
        <div
            data-attr="insight-empty-state"
            className="flex flex-col items-center gap-2 justify-center rounded p-4 h-full w-full"
        >
            <IconErrorOutline className="text-5xl shrink-0" />

            <h2 className="text-xl text-danger leading-tight mb-6" data-attr="insight-loading-too-long">
                {/* Note that this default phrasing signals the issue is intermittent, */}
                {/* and that perhaps the query will complete on retry */}
                {title || <span>There was a problem completing this query</span>}
            </h2>

            {!excludeDetail && (
                <div className="mt-4">
                    We apologize for this unexpected situation. There are a couple of things you can do:
                    <ol>
                        <li>
                            First and foremost you can <b>try again</b>. We recommend you wait a moment before doing so.
                        </li>
                        <li>
                            <Link
                                data-attr="insight-error-bug-report"
                                onClick={() => {
                                    openSupportForm({ kind: 'bug', target_area: 'analytics' })
                                }}
                            >
                                If this persists, submit a bug report.
                            </Link>
                        </li>
                    </ol>
                </div>
            )}

            {!excludeActions && (
                <div className="flex gap-2 mt-4">
                    {onRetry ? <RetryButton onRetry={onRetry} query={query} /> : <QueryDebuggerButton query={query} />}
                    {fixWithAIComponent ?? null}
                </div>
            )}
            <QueryIdDisplay queryId={queryId} />
        </div>
    )
}

type FunnelSingleStepStateProps = { actionable?: boolean }

export function FunnelSingleStepState({ actionable = true }: FunnelSingleStepStateProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { series } = useValues(funnelDataLogic(insightProps))
    const { updateQuerySource } = useActions(funnelDataLogic(insightProps))

    const filters = series ? seriesToActionsAndEvents(series) : {}
    const setFilters = (payload: Partial<FilterType>): void => {
        updateQuerySource({
            series: actionsAndEventsToSeries(payload as any, true, MathAvailability.None),
        } as Partial<FunnelsQuery>)
    }

    const { addFilter } = useActions(entityFilterLogic({ setFilters, filters, typeKey: 'EditFunnel-action' }))

    return (
        <div
            data-attr="insight-empty-state"
            className="flex flex-col flex-1 items-center justify-center text-center text-balance"
        >
            <div className="text-5xl text-muted mb-2">
                <IconPlusSquare />
            </div>
            <h2 className="text-xl leading-tight font-medium">Add another step!</h2>
            <p className="mb-0 text-sm text-muted">
                <span>You're almost there! Funnels require at least two steps before calculating.</span>
                {actionable && (
                    <>
                        <br />
                        <span>Once you have two steps defined, additional changes will recalculate automatically.</span>
                    </>
                )}
            </p>
            {actionable && (
                <div className="flex justify-center mt-4">
                    <LemonButton
                        size="large"
                        type="secondary"
                        onClick={() => addFilter()}
                        data-attr="add-action-event-button-empty-state"
                        icon={<IconPlus />}
                    >
                        Add funnel step
                    </LemonButton>
                </div>
            )}
            <div className="mt-4">
                <Link
                    data-attr="funnels-single-step-help"
                    to="https://posthog.com/docs/user-guides/funnels?utm_medium=in-product&utm_campaign=funnel-empty-state"
                    target="_blank"
                    className="flex items-center justify-center"
                    targetBlankIcon
                >
                    Learn more about funnels in PostHog docs
                </Link>
            </div>
        </div>
    )
}

const SAVED_INSIGHTS_COPY = {
    [`${SavedInsightsTabs.All}`]: {
        title: 'There are no insights $CONDITION.',
        description: 'Once you create an insight, it will show up here.',
    },
    [`${SavedInsightsTabs.Yours}`]: {
        title: "You haven't created insights $CONDITION.",
        description: 'Once you create an insight, it will show up here.',
    },
    [`${SavedInsightsTabs.Favorites}`]: {
        title: 'There are no favorited insights $CONDITION.',
        description: 'Once you favorite an insight, it will show up here.',
    },
}

export function SavedInsightsEmptyState({
    filters,
    usingFilters,
}: {
    filters: SavedInsightFilters
    usingFilters?: boolean
}): JSX.Element {
    // show the search string that was used to make the results, not what it currently is
    const searchString = filters?.search || null
    const { title, description } = SAVED_INSIGHTS_COPY[filters.tab as keyof typeof SAVED_INSIGHTS_COPY] ?? {}

    return (
        <div
            data-attr="insight-empty-state"
            className="saved-insight-empty-state flex flex-col flex-1 items-center justify-center"
        >
            <div className="illustration-main w-40 m-auto">
                <BuilderHog3 className="w-full h-full" />
            </div>
            <h2>
                {usingFilters
                    ? searchString
                        ? title.replace('$CONDITION', `matching "${searchString}"`)
                        : title.replace('$CONDITION', `matching these filters`)
                    : title.replace('$CONDITION', 'for this project')}
            </h2>
            {usingFilters ? (
                <p className="empty-state__description">
                    Refine your keyword search, or try using other filters such as type, last modified or created by.
                </p>
            ) : (
                <p className="empty-state__description">{description}</p>
            )}
            {filters.tab !== SavedInsightsTabs.Favorites && (
                <div className="flex justify-center">
                    <Link to={urls.insightNew()}>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Insight}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                data-attr="add-insight-button-empty-state"
                                icon={<IconPlusSmall />}
                                className="add-insight-button"
                            >
                                New insight
                            </LemonButton>
                        </AccessControlAction>
                    </Link>
                </div>
            )}
        </div>
    )
}
