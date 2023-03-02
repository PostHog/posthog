import { useActions, useValues } from 'kea'
import { PlusCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { IconErrorOutline, IconOpenInNew, IconPlus, IconTrendUp } from 'lib/lemon-ui/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { Button, Empty } from 'antd'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { InsightLogicProps, InsightType, SavedInsightsTabs } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import clsx from 'clsx'
import './EmptyStates.scss'
import { urls } from 'scenes/urls'
import { Link } from 'lib/lemon-ui/Link'
import { Animation } from 'lib/components/Animation/Animation'
import { AnimationType } from 'lib/animations/animations'
import { LemonButton } from '@posthog/lemon-ui'
import { samplingFilterLogic } from '../EditorFilters/samplingFilterLogic'

export function InsightEmptyState(): JSX.Element {
    return (
        <div className="insight-empty-state">
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="" />
                </div>
                <h2>There are no matching events for this query</h2>
                <p className="text-center">Try changing the date range, or pick another action, event or breakdown.</p>
            </div>
        </div>
    )
}

export function InsightTimeoutState({
    isLoading,
    queryId,
    insightProps,
    insightType,
}: {
    isLoading: boolean
    queryId?: string | null
    insightProps: InsightLogicProps
    insightType?: InsightType
}): JSX.Element {
    const _samplingFilterLogic = samplingFilterLogic({ insightType, insightProps })

    const { setSamplingPercentage } = useActions(_samplingFilterLogic)
    const { suggestedSamplingPercentage, samplingAvailable } = useValues(_samplingFilterLogic)

    const speedUpBySamplingAvailable = samplingAvailable && suggestedSamplingPercentage
    return (
        <div className="insight-empty-state warning">
            <div className="empty-state-inner">
                <div className="illustration-main" style={{ height: 'auto' }}>
                    {isLoading ? <Animation type={AnimationType.SportsHog} /> : <IconErrorOutline />}
                </div>
                {isLoading ? (
                    <div className="m-auto text-center">
                        Your query is taking a long time to complete. <b>We're still working on it.</b>
                        <br />
                        {speedUpBySamplingAvailable ? 'See below some options to speed things up.' : ''}
                        <br />
                    </div>
                ) : (
                    <h2>Your query took too long to complete</h2>
                )}
                {isLoading && speedUpBySamplingAvailable ? (
                    <div>
                        <LemonButton
                            className="mx-auto mt-4"
                            type="primary"
                            onClick={() => setSamplingPercentage(suggestedSamplingPercentage)}
                        >
                            Click here to speed up calculation with {suggestedSamplingPercentage}% sampling
                        </LemonButton>
                        <br />
                    </div>
                ) : null}
                <p className="m-auto text-center">
                    In order to improve the performance of the query, you can {speedUpBySamplingAvailable ? 'also' : ''}{' '}
                    try to reduce the date range of your query, remove breakdowns, or get in touch with us by{' '}
                    <a
                        data-attr="insight-timeout-raise-issue"
                        href="https://github.com/PostHog/posthog/issues/new?labels=performance&template=performance_issue_report.md"
                        target="_blank"
                        rel="noreferrer noopener"
                    >
                        raising an issue
                    </a>{' '}
                    in our GitHub repository or messaging us{' '}
                    <a
                        data-attr="insight-timeout-slack"
                        href="https://posthog.com/slack"
                        rel="noopener noreferrer"
                        target="_blank"
                    >
                        on Slack
                    </a>
                    .
                </p>
                {!!queryId ? <div className="text-muted text-xs">Query ID: {queryId}</div> : null}
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
    return (
        <div className={clsx(['insight-empty-state', 'error', { 'match-container': excludeDetail }])}>
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <IconErrorOutline />
                </div>
                <h2>{title || 'There was an error completing this query'}</h2>
                {!excludeDetail && (
                    <div className="mt-4">
                        We apologize for this unexpected situation. There are a few things you can do:
                        <ol>
                            <li>
                                First and foremost you can <b>try again</b>. We recommended you wait a few moments
                                before doing so.
                            </li>
                            <li>
                                <a
                                    data-attr="insight-error-raise-issue"
                                    href="https://github.com/PostHog/posthog/issues/new?labels=bug&template=bug_report.md"
                                    target="_blank"
                                    rel="noreferrer noopener"
                                >
                                    Raise an issue
                                </a>{' '}
                                in our GitHub repository.
                            </li>
                            <li>
                                Get in touch with us{' '}
                                <a
                                    data-attr="insight-error-slack"
                                    href="https://posthog.com/slack"
                                    rel="noopener noreferrer"
                                    target="_blank"
                                >
                                    on Slack
                                </a>
                                .
                            </li>
                            <li>
                                Email us at{' '}
                                <a
                                    data-attr="insight-error-email"
                                    href="mailto:hey@posthog.com?subject=Insight%20graph%20error"
                                >
                                    hey@posthog.com
                                </a>
                                .
                            </li>
                        </ol>
                    </div>
                )}
                {!!queryId ? <div className="text-muted text-xs">Query ID: {queryId}</div> : null}
            </div>
        </div>
    )
}

export function FunnelSingleStepState({ actionable = true }: { actionable?: boolean }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    const { addFilter } = useActions(entityFilterLogic({ setFilters, filters, typeKey: 'EditFunnel-action' }))

    return (
        <div className="insight-empty-state funnels-empty-state">
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <PlusCircleOutlined />
                </div>
                <h2 className="funnels-empty-state__title">Add another step!</h2>
                <p className="funnels-empty-state__description">
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
                <div className="illustration-main">
                    <IconTrendUp />
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
                        Refine your keyword search, or try using other filters such as type, last modified or
                        created by.
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
