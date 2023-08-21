import { useActions, useValues } from 'kea'
import { PlusCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { IconErrorOutline, IconOpenInNew, IconPlus } from 'lib/lemon-ui/icons'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { Button, Empty } from 'antd'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { FilterType, InsightLogicProps, SavedInsightsTabs } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import './EmptyStates.scss'
import { urls } from 'scenes/urls'
import { Link } from 'lib/lemon-ui/Link'
import { LemonButton } from '@posthog/lemon-ui'
import { samplingFilterLogic } from '../EditorFilters/samplingFilterLogic'
import { posthog } from 'posthog-js'
import { seriesToActionsAndEvents } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { FunnelsQuery } from '~/queries/schema'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { BuilderHog3 } from 'lib/components/hedgehogs'

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
                <div className="illustration-main">
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="" />
                </div>
                <h2>{heading}</h2>
                <p className="text-center">{detail}</p>
            </div>
        </div>
    )
}

export function InsightTimeoutState({
    isLoading,
    queryId,
    insightProps,
}: {
    isLoading: boolean
    queryId?: string | null
    insightProps: InsightLogicProps
}): JSX.Element {
    const { setSamplingPercentage } = useActions(samplingFilterLogic(insightProps))
    const { suggestedSamplingPercentage } = useValues(samplingFilterLogic(insightProps))

    return (
        <div className="insight-empty-state warning">
            <div className="empty-state-inner">
                {!isLoading && (
                    <>
                        <div className="illustration-main">
                            <IconErrorOutline />
                        </div>
                        <h2>Your query took too long to complete</h2>
                    </>
                )}
                {isLoading && suggestedSamplingPercentage ? (
                    <div>
                        <LemonButton
                            className="mx-auto mt-4"
                            type="primary"
                            onClick={() => {
                                setSamplingPercentage(suggestedSamplingPercentage)
                                posthog.capture('sampling_enabled_on_slow_query', {
                                    samplingPercentage: suggestedSamplingPercentage,
                                })
                            }}
                        >
                            Click here to speed up calculation with {suggestedSamplingPercentage}% sampling
                        </LemonButton>
                        <br />
                    </div>
                ) : null}
                <p className="m-auto text-center">
                    In order to improve the performance of the query, you can{' '}
                    {suggestedSamplingPercentage ? 'also' : ''} try to reduce the date range of your query, or remove
                    breakdowns.
                </p>
                {queryId ? <div className="text-muted text-xs m-auto text-center">Query ID: {queryId}</div> : null}
            </div>
        </div>
    )
}

export interface InsightErrorStateProps {
    excludeDetail?: boolean
    title?: string
    queryId?: string | null
}

export function InsightErrorState({ excludeDetail, title, queryId }: InsightErrorStateProps): JSX.Element {
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
                <h2>{title || 'There was an error completing this query'}</h2>
                {!excludeDetail && (
                    <div className="mt-4">
                        We apologize for this unexpected situation. There are a couple of things you can do:
                        <ol>
                            <li>
                                First and foremost you can <b>try again</b>. We recommended you wait a few moments
                                before doing so.
                            </li>
                            <li>
                                <Link
                                    data-attr="insight-error-bug-report"
                                    onClick={() => {
                                        openSupportForm('bug', 'analytics')
                                    }}
                                >
                                    If this persists, submit a bug report.
                                </Link>
                            </li>
                        </ol>
                    </div>
                )}
                {queryId ? <div className="text-muted text-xs text-center">Query ID: {queryId}</div> : null}
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
        updateQuerySource({ series: actionsAndEventsToSeries(payload as any) } as Partial<FunnelsQuery>)
    }

    const { addFilter } = useActions(entityFilterLogic({ setFilters, filters, typeKey: 'EditFunnel-action' }))

    return (
        <div className="insight-empty-state funnels-empty-state">
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <PlusCircleOutlined />
                </div>
                <h2 className="funnels-empty-state__title">Add another step!</h2>
                <p className="text-center">
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
                    <a
                        data-attr="funnels-single-step-help"
                        href="https://posthog.com/docs/user-guides/funnels?utm_medium=in-product&utm_campaign=funnel-empty-state"
                        target="_blank"
                        rel="noopener"
                        className="flex items-center justify-center"
                    >
                        Learn more about funnels in PostHog docs
                        <IconOpenInNew style={{ marginLeft: 4, fontSize: '0.85em' }} />
                    </a>
                </div>
            </div>
        </div>
    )
}

export function FunnelInvalidExclusionState(): JSX.Element {
    return (
        <div className="insight-empty-state warning">
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <WarningOutlined />
                </div>
                <h2>Invalid exclusion filters</h2>
                <p>
                    You're excluding events or actions that are part of the funnel steps. Try changing your funnel step
                    filters, or removing the overlapping exclusion event.
                </p>
                <div className="mt-4">
                    <a
                        data-attr="insight-funnels-emptystate-help"
                        href="https://posthog.com/docs/user-guides/funnels?utm_medium=in-product&utm_campaign=funnel-exclusion-filter-state"
                        target="_blank"
                        rel="noopener"
                    >
                        Learn more about funnels in PostHog docs
                        <IconOpenInNew style={{ marginLeft: 4, fontSize: '0.85em' }} />
                    </a>
                </div>
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
                    <Link to={urls.insightNew()}>
                        <Button
                            size="large"
                            type="primary"
                            data-attr="add-insight-button-empty-state"
                            icon={<PlusCircleOutlined />}
                            className="add-insight-button"
                        >
                            New Insight
                        </Button>
                    </Link>
                )}
            </div>
        </div>
    )
}
