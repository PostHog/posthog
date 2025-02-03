import './EmptyStates.scss'

import { IconArchive, IconPieChart, IconPlus, IconPlusSmall, IconPlusSquare, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { BuilderHog3 } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { dayjs } from 'lib/dayjs'
import { IconErrorOutline, IconOpenInNew } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber, humanizeBytes, inStorybook, inStorybookTestRunner } from 'lib/utils'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelsQuery, Node, QueryStatus } from '~/queries/schema'
import { FilterType, InsightLogicProps, SavedInsightsTabs } from '~/types'

import { samplingFilterLogic } from '../EditorFilters/samplingFilterLogic'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightDataLogic } from '../insightDataLogic'

export function InsightEmptyState({
    heading = 'There are no matching events for this query',
    detail = 'Try changing the date range, or pick another action, event or breakdown.',
}: {
    heading?: string
    detail?: string
}): JSX.Element {
    return (
        <div
            data-attr="insight-empty-state"
            className="insights-empty-state rounded p-4 m-2 h-full w-full flex flex-col items-center justify-center"
        >
            <IconArchive className="text-5xl mb-2 text-tertiary" />
            <h2 className="text-xl leading-tight">{heading}</h2>
            <p className="text-sm text-center text-balance">{detail}</p>
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

function QueryIdDisplay({
    queryId,
    compact = false,
}: {
    queryId?: string | null
    compact?: boolean
}): JSX.Element | null {
    if (queryId == null) {
        return null
    }

    return (
        <div className={clsx('text-muted text-xs', { 'mt-20': !compact })}>
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
            className="max-w-80 mt-4"
        >
            Open in query debugger
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
]

export function StatelessInsightLoadingState({
    queryId,
    pollResponse,
    suggestion,
    compact = false,
}: {
    queryId?: string | null
    pollResponse?: Record<string, QueryStatus | null> | null
    suggestion?: JSX.Element
    compact?: boolean
}): JSX.Element {
    const [rowsRead, setRowsRead] = useState(0)
    const [bytesRead, setBytesRead] = useState(0)
    const [secondsElapsed, setSecondsElapsed] = useState(0)

    const [loadingMessageIndex, setLoadingMessageIndex] = useState(() =>
        inStorybook() || inStorybookTestRunner() ? 0 : Math.floor(Math.random() * LOADING_MESSAGES.length)
    )
    const [isLoadingMessageVisible, setIsLoadingMessageVisible] = useState(true)

    useEffect(() => {
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
    }, [pollResponse])

    // Toggle between loading messages every 3 seconds, with 300ms fade out, then change text, keep in sync with the transition duration below
    useEffect(() => {
        const TOGGLE_INTERVAL = 3000
        const FADE_OUT_DURATION = 300

        // Don't toggle loading messages in storybook, will make tests flaky if so
        if (inStorybook() || inStorybookTestRunner()) {
            return
        }

        const interval = setInterval(() => {
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
        }, TOGGLE_INTERVAL)

        return () => clearInterval(interval)
    }, [])

    const bytesPerSecond = (bytesRead / (secondsElapsed || 1)) * 1000
    const estimatedRows = pollResponse?.status?.query_progress?.estimated_rows_total

    const cpuUtilization =
        (pollResponse?.status?.query_progress?.active_cpu_time || 0) /
        (pollResponse?.status?.query_progress?.time_elapsed || 1) /
        10000

    return (
        <div data-attr="insight-empty-state" className="insights-empty-state rounded p-4 m-2 h-full w-full">
            <div className="flex flex-col gap-1">
                <span
                    className={clsx(
                        'font-bold transition-opacity duration-300',
                        isLoadingMessageVisible ? 'opacity-100' : 'opacity-0'
                    )}
                >
                    {LOADING_MESSAGES[loadingMessageIndex]}
                </span>
                {suggestion ? (
                    suggestion
                ) : (
                    <div className="flex gap-3">
                        <p className="text-xs m-0">Need to speed things up? Try reducing the date range.</p>
                    </div>
                )}
            </div>

            <LoadingBar />
            <p className="mx-auto text-center text-xs">
                {rowsRead > 0 && bytesRead > 0 && (
                    <>
                        <span>{humanFriendlyNumber(rowsRead || 0, 0)} </span>
                        <span>
                            {estimatedRows && estimatedRows >= rowsRead ? (
                                <span>/ ${humanFriendlyNumber(estimatedRows)} </span>
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

            <QueryIdDisplay queryId={queryId} compact={compact} />
        </div>
    )
}

export function InsightLoadingState({
    queryId,
    insightProps,
}: {
    queryId?: string | null
    insightProps: InsightLogicProps
}): JSX.Element {
    const { suggestedSamplingPercentage, samplingPercentage } = useValues(samplingFilterLogic(insightProps))
    const { insightPollResponse } = useValues(insightDataLogic(insightProps))
    const { currentTeam } = useValues(teamLogic)

    const personsOnEventsMode =
        currentTeam?.modifiers?.personsOnEventsMode ?? currentTeam?.default_modifiers?.personsOnEventsMode ?? 'disabled'

    return (
        <StatelessInsightLoadingState
            queryId={queryId}
            pollResponse={insightPollResponse}
            suggestion={
                <div className="flex items-center rounded gap-x-3 max-w-120 m-2">
                    {personsOnEventsMode === 'person_id_override_properties_joined' ? (
                        <>
                            <p className="text-xs m-0">
                                You can speed this query up by changing the{' '}
                                <Link to="/settings/project#persons-on-events">person properties mode</Link> setting.
                            </p>
                        </>
                    ) : (
                        <>
                            <p className="text-xs m-0">
                                {suggestedSamplingPercentage && !samplingPercentage ? (
                                    <span data-attr="insight-loading-waiting-message">
                                        Need to speed things up? Try reducing the date range, removing breakdowns, or
                                        turning on <SamplingLink insightProps={insightProps} /> to speed things up.
                                    </span>
                                ) : suggestedSamplingPercentage && samplingPercentage ? (
                                    <>
                                        Still waiting around? You must have lots of data! Kick it up a notch with{' '}
                                        <SamplingLink insightProps={insightProps} />. Or try reducing the date range and
                                        removing breakdowns.
                                    </>
                                ) : (
                                    <>Need to speed things up? Try reducing the date range or removing breakdowns.</>
                                )}
                            </p>
                        </>
                    )}
                </div>
            }
        />
    )
}

export function InsightTimeoutState({ queryId }: { queryId?: string | null }): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    return (
        <div data-attr="insight-empty-state" className="insights-empty-state rounded p-4 m-2 h-full w-full">
            <h2 className="text-xl leading-tight mb-6">
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

export function InsightValidationError({ detail, query }: { detail: string; query?: Record<string, any> | null }): JSX.Element {
    return (
        <div
            data-attr="insight-empty-state"
            className="insights-empty-state flex flex-col items-center justify-center gap-2 rounded p-4 m-2 h-full w-full"
        >
            <IconWarning className="text-5xl shrink-0" />

            <h2
                data-attr="insight-loading-too-long"
                className="text-xl leading-tight"
                // TODO: Use an actual `text-warning` color once @adamleithp changes are live
                // eslint-disable-next-line react/forbid-dom-props
                style={{ color: 'var(--warning)' }}
            >
                There is a problem with this query
                {/* Note that this phrasing above signals the issue is not intermittent, */}
                {/* but rather that it's something with the definition of the query itself */}
            </h2>

            <p className="text-sm text-balance">{detail}</p>
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
    excludeDetail?: boolean
    title?: string
    query?: Record<string, any> | Node | null
    queryId?: string | null
}

export function InsightErrorState({ excludeDetail, title, query, queryId }: InsightErrorStateProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    if (!preflight?.cloud) {
        excludeDetail = true // We don't provide support for self-hosted instances
    }

    return (
        <div
            data-attr="insight-empty-state"
            className="insights-empty-state flex flex-col items-center gap-2 justify-center rounded p-4 m-2 h-full w-full"
        >
            <IconErrorOutline className="text-5xl shrink-0" />

            <h2
                className="text-xl leading-tight mb-6"
                // TODO: Use an actual `text-danger` color once @adamleithp changes are live
                // eslint-disable-next-line react/forbid-dom-props
                style={{ color: 'var(--danger)' }}
                data-attr="insight-loading-too-long"
            >
                {title || <span>There was a problem completing this query</span>}
                {/* Note that this default phrasing above signals the issue is intermittent, */}
                {/* and that perhaps the query will complete on retry */}
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

            <QueryDebuggerButton query={query} />
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
        <div data-attr="insight-empty-state" className="flex flex-col flex-1 items-center justify-center m-2">
            <div className="text-5xl text-muted mb-2">
                <IconPlusSquare />
            </div>
            <h2 className="text-xl leading-tight font-medium">Add another step!</h2>
            <p className="mb-0 text-sm text-center text-balance text-muted">
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

export function SavedInsightsEmptyState(): JSX.Element {
    const {
        filters: { tab },
        insights,
        usingFilters,
    } = useValues(savedInsightsLogic)

    // show the search string that was used to make the results, not what it currently is
    const searchString = insights.filters?.search || null
    const { title, description } = SAVED_INSIGHTS_COPY[tab] ?? {}

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
            {tab !== SavedInsightsTabs.Favorites && (
                <div className="flex justify-center">
                    <Link to={urls.insightNew()}>
                        <LemonButton
                            type="primary"
                            data-attr="add-insight-button-empty-state"
                            icon={<IconPlusSmall />}
                            className="add-insight-button"
                        >
                            New insight
                        </LemonButton>
                    </Link>
                </div>
            )}
        </div>
    )
}
