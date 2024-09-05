import './EmptyStates.scss'

import {
    IconArchive,
    IconInfo,
    IconPieChart,
    IconPlus,
    IconPlusSmall,
    IconPlusSquare,
    IconWarning,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { BuilderHog3 } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { IconErrorOutline, IconOpenInNew } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils'
import posthog from 'posthog-js'
import React, { useEffect, useState } from 'react'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelsQuery, Node } from '~/queries/schema'
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
        <div className="insight-empty-state">
            <div className="empty-state-inner">
                <IconArchive className="text-5xl mb-2 text-secondary-3000" />
                <h2 className="text-xl leading-tight">{heading}</h2>
                <p className="text-sm text-center text-balance">{detail}</p>
            </div>
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
function humanFileSize(size: number): string {
    const i = size == 0 ? 0 : Math.floor(Math.log(size) / Math.log(1024))
    return (+(size / Math.pow(1024, i))).toFixed(2) + ' ' + ['B', 'kB', 'MB', 'GB', 'TB'][i]
}

export function InsightLoadingStateWithLoadingBar({
    queryId,
    insightProps,
}: {
    queryId?: string | null
    insightProps: InsightLogicProps
}): JSX.Element {
    const { suggestedSamplingPercentage, samplingPercentage } = useValues(samplingFilterLogic(insightProps))
    const { insightPollResponse } = useValues(insightDataLogic(insightProps))

    const [rowsRead, setRowsRead] = useState(0)
    const [bytesRead, setBytesRead] = useState(0)
    const [secondsElapsed, setSecondsElapsed] = useState(0)

    useEffect(() => {
        const status = insightPollResponse?.status?.query_progress
        const previousStatus = insightPollResponse?.previousStatus?.query_progress
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
                return dayjs().diff(dayjs(insightPollResponse?.status?.start_time), 'milliseconds')
            })
        }, 100)

        return () => clearInterval(interval)
    }, [insightPollResponse])
    const bytesPerSecond = (bytesRead / (secondsElapsed || 1)) * 1000
    const estimatedRows = insightPollResponse?.status?.query_progress?.estimated_rows_total

    const cpuUtilization =
        (insightPollResponse?.status?.query_progress?.active_cpu_time || 0) /
        (insightPollResponse?.status?.query_progress?.time_elapsed || 1) /
        10000

    return (
        <div className="insight-empty-state warning">
            <div className="empty-state-inner">
                <p className="mx-auto text-center">Crunching through hogloads of data...</p>
                <LoadingBar />
                <p className="mx-auto text-center text-xs">
                    {rowsRead > 0 && bytesRead > 0 && (
                        <>
                            {humanFriendlyNumber(rowsRead || 0, 0)}{' '}
                            {estimatedRows && estimatedRows >= rowsRead
                                ? `/ ${humanFriendlyNumber(estimatedRows)} `
                                : null}{' '}
                            rows
                            <br />
                            {humanFileSize(bytesRead || 0)} ({humanFileSize(bytesPerSecond || 0)}/s)
                            <br />
                            CPU {humanFriendlyNumber(cpuUtilization, 0)}%
                        </>
                    )}
                </p>
                <div className="p-4 rounded bg-bg-3000 flex gap-x-2 max-w-120">
                    <div className="flex">
                        <IconInfo className="w-4 h-4" />
                    </div>
                    <p className="text-xs m-0 leading-5">
                        {suggestedSamplingPercentage && !samplingPercentage ? (
                            <span data-attr="insight-loading-waiting-message">
                                Need to speed things up? Try reducing the date range, removing breakdowns, or turning on{' '}
                                <SamplingLink insightProps={insightProps} />.
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
                </div>
                {queryId ? (
                    <div className="text-muted text-xs mx-auto text-center mt-6">Query ID: {queryId}</div>
                ) : null}
            </div>
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
    const { featureFlags } = useValues(featureFlagLogic)
    const { suggestedSamplingPercentage, samplingPercentage } = useValues(samplingFilterLogic(insightProps))

    if (featureFlags[FEATURE_FLAGS.INSIGHT_LOADING_BAR]) {
        return <InsightLoadingStateWithLoadingBar queryId={queryId} insightProps={insightProps} />
    }

    return (
        <div className="insight-empty-state warning">
            <Animation type={AnimationType.LaptopHog} />
            <div className="empty-state-inner">
                <p className="mx-auto text-center">Crunching through hogloads of data...</p>
                <div className="p-4 rounded bg-bg-3000 flex gap-x-2 max-w-120">
                    <div className="flex">
                        <IconInfo className="w-4 h-4" />
                    </div>
                    <p className="text-xs m-0 leading-5">
                        {suggestedSamplingPercentage && !samplingPercentage ? (
                            <span data-attr="insight-loading-waiting-message">
                                Need to speed things up? Try reducing the date range, removing breakdowns, or turning on{' '}
                                <SamplingLink insightProps={insightProps} />.
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
                </div>
                {queryId ? (
                    <div className="text-muted text-xs mx-auto text-center mt-6">Query ID: {queryId}</div>
                ) : null}
            </div>
        </div>
    )
}

export function InsightTimeoutState({ queryId }: { queryId?: string | null }): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    return (
        <div className="insight-empty-state warning">
            <div className="empty-state-inner">
                <>
                    <div className="illustration-main">
                        <IconErrorOutline />
                    </div>
                    <h2 className="text-xl leading-tight mb-6">Your query took too long to complete</h2>
                </>
                <div className="p-4 rounded bg-bg-3000 flex gap-x-2 max-w-120">
                    <div className="flex">
                        <IconInfo className="w-4 h-4" />
                    </div>
                    <p className="text-xs m-0 leading-5">
                        <>
                            Sometimes this happens. Try refreshing the page, reducing the date range, or removing
                            breakdowns. If you're still having issues,{' '}
                            <Link
                                onClick={() => {
                                    openSupportForm({ kind: 'bug', target_area: 'analytics' })
                                }}
                            >
                                let us know
                            </Link>
                            .
                        </>
                    </p>
                </div>
                {queryId ? (
                    <div className="text-muted text-xs mx-auto text-center mt-6">Query ID: {queryId}</div>
                ) : null}
            </div>
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
        <div className="insight-empty-state error">
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <IconErrorOutline />
                </div>
                <h2 className="text-xl leading-tight">{title || 'There was a problem completing this query'}</h2>
                {/* Note that this default phrasing above signals the issue is intermittent, */}
                {/* and that perhaps the query will complete on retry */}
                {!excludeDetail && (
                    <div className="mt-4">
                        We apologize for this unexpected situation. There are a couple of things you can do:
                        <ol>
                            <li>
                                First and foremost you can <b>try again</b>. We recommend you wait a moment before doing
                                so.
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
                {queryId ? <div className="text-muted text-xs text-center">Query ID: {queryId}</div> : null}
                {query && (
                    <LemonButton
                        data-attr="insight-error-query"
                        targetBlank
                        size="small"
                        type="secondary"
                        to={urls.debugQuery(query)}
                        className="mt-4"
                    >
                        Open in query debugger
                    </LemonButton>
                )}
            </div>
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
        <div className="insight-empty-state funnels-empty-state">
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <IconPlusSquare />
                </div>
                <h2 className="text-xl leading-tight funnels-empty-state__title">Add another step!</h2>
                <p className="mb-0 text-sm text-center text-balance">
                    You’re almost there! Funnels require at least two steps before calculating.
                    {actionable &&
                        ' Once you have two steps defined, additional changes will recalculate automatically.'}
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
        <div className="insight-empty-state warning">
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <IconWarning />
                </div>
                <h2 className="text-xl leading-tight" data-attr="insight-loading-too-long">
                    There is a problem with this query
                    {/* Note that this phrasing above signals the issue is not intermittent, */}
                    {/* but rather that it's something with the definition of the query itself */}
                </h2>
                <p className="text-sm text-center text-balance">{detail}</p>
                {query ? (
                    <p className="text-center text-balance">
                        <LemonButton
                            data-attr="insight-error-query"
                            targetBlank
                            size="small"
                            type="secondary"
                            to={urls.debugQuery(query)}
                        >
                            Open in query debugger
                        </LemonButton>
                    </p>
                ) : null}
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
        <div className="saved-insight-empty-state">
            <div className="empty-state-inner">
                <div className="illustration-main w-40 m-auto">
                    <BuilderHog3 className="w-full h-full" />
                </div>
                <h2 className="empty-state__title">
                    {usingFilters
                        ? searchString
                            ? title.replace('$CONDITION', `matching "${searchString}"`)
                            : title.replace('$CONDITION', `matching these filters`)
                        : title.replace('$CONDITION', 'for this project')}
                </h2>
                {usingFilters ? (
                    <p className="empty-state__description">
                        Refine your keyword search, or try using other filters such as type, last modified or created
                        by.
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
        </div>
    )
}
