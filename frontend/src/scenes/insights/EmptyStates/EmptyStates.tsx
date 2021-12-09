import { useActions, useValues } from 'kea'
import React from 'react'
import { LoadingOutlined, PlusCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { IllustrationDanger, IconTrendUp, IconExternalLinkBold } from 'lib/components/icons'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { entityFilterLogic } from 'scenes/insights/ActionFilter/entityFilterLogic'
import { Button, Empty } from 'antd'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { SavedInsightsTabs } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import clsx from 'clsx'

export const UNNAMED_INSIGHT_NAME = 'Unnamed insight'

export function InsightEmptyState({ color, isDashboard }: { color?: string; isDashboard?: boolean }): JSX.Element {
    return (
        <div className={clsx('insight-empty-state', { 'is-dashboard': isDashboard }, color)}>
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="" />
                </div>
                <h2>There are no matching events for this query</h2>
                <p className="text-center">Try changing the date range or pick another action, event, or breakdown.</p>
            </div>
        </div>
    )
}

export function InsightTimeoutState({ isLoading }: { isLoading: boolean }): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    return (
        <div className="insight-empty-state warning">
            <div className="empty-state-inner">
                <div className="illustration-main">{isLoading ? <LoadingOutlined spin /> : <IllustrationDanger />}</div>
                <h2>{isLoading ? 'Looks like things are a little slow…' : 'Your query took too long to complete'}</h2>
                {isLoading ? (
                    <>
                        Your query is taking a long time to complete. <b>We're still working on it.</b> However, here
                        are some things you can try to speed it up:
                    </>
                ) : (
                    <>
                        Here are some things you can try to speed up your query and <b>try again</b>:
                    </>
                )}
                <ol>
                    <li>Reduce the date range of your query.</li>
                    <li>Remove some filters.</li>
                    {!preflight?.cloud && <li>Increase the size of your database server.</li>}
                    {!preflight?.cloud && !preflight?.is_clickhouse_enabled && (
                        <li>
                            <a
                                data-attr="insight-timeout-upgrade-to-clickhouse"
                                href="https://posthog.com/docs/self-host#deployment-options?utm_medium=in-product&utm_campaign=insight-timeout-empty-state"
                                rel="noopener"
                                target="_blank"
                            >
                                Switch to Clickhouse backend
                            </a>{' '}
                            (engineered for scale, and you'll get more features)
                        </li>
                    )}
                    <li>
                        <a
                            data-attr="insight-timeout-raise-issue"
                            href="https://github.com/PostHog/posthog/issues/new?labels=performance&template=performance_issue_report.md"
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
                            data-attr="insight-timeout-slack"
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
                        <a data-attr="insight-timeout-email" href="mailto:hey@posthog.com">
                            hey@posthog.com
                        </a>
                        .
                    </li>
                </ol>
            </div>
        </div>
    )
}

export interface InsightErrorStateProps {
    excludeDetail?: boolean
    title?: string
}

export function InsightErrorState({ excludeDetail, title }: InsightErrorStateProps): JSX.Element {
    return (
        <div className={clsx(['insight-empty-state', 'error', { 'match-container': excludeDetail }])}>
            <div className="empty-state-inner">
                <div className="illustration-main">
                    <IllustrationDanger />
                </div>
                <h2>{title || 'There was an error completing this query'}</h2>
                {!excludeDetail && (
                    <div className="mt">
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
            </div>
        </div>
    )
}

export function FunnelSingleStepState(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters, clickhouseFeaturesEnabled } = useValues(funnelLogic(insightProps))
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
                    {clickhouseFeaturesEnabled
                        ? ' Once you have two steps defined, additional changes will recalculate automatically.'
                        : ''}
                </p>
                <div className="mt text-center">
                    <Button
                        size="large"
                        onClick={() => addFilter()}
                        data-attr="add-action-event-button-empty-state"
                        icon={<PlusCircleOutlined />}
                        className="add-action-event-button"
                    >
                        Add funnel step
                    </Button>
                </div>
                <div className="mt text-center">
                    <a
                        data-attr="funnels-single-step-help"
                        href="https://posthog.com/docs/user-guides/funnels?utm_medium=in-product&utm_campaign=funnel-empty-state"
                        target="_blank"
                        rel="noopener"
                        className="flex-center"
                        style={{ justifyContent: 'center' }}
                    >
                        Learn more about funnels in our support documentation
                        <IconExternalLinkBold style={{ marginLeft: 4, fontSize: '0.85em' }} />
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
                <div className="mt text-center">
                    <a
                        data-attr="insight-funnels-emptystate-help"
                        href="https://posthog.com/docs/user-guides/funnels?utm_medium=in-product&utm_campaign=funnel-exclusion-filter-state"
                        target="_blank"
                        rel="noopener"
                    >
                        Learn more about funnels in our support documentation
                        <IconExternalLinkBold style={{ marginLeft: 4, fontSize: '0.85em' }} />
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
    const { addGraph } = useActions(savedInsightsLogic)
    const {
        filters: { tab },
        insights,
        usingFilters,
    } = useValues(savedInsightsLogic)

    // show the search string that was used to make the results, not what it currently is
    const searchString = insights.filters?.search || null
    const { title, description } = SAVED_INSIGHTS_COPY[tab]

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
                <p className="empty-state__description">{description}</p>
                {tab !== SavedInsightsTabs.Favorites && (
                    <Button
                        size="large"
                        type="primary"
                        onClick={() => addGraph('Trends')} // Add trends graph by default
                        data-attr="add-insight-button-empty-state"
                        icon={<PlusCircleOutlined />}
                        className="add-insight-button"
                    >
                        New Insight
                    </Button>
                )}
            </div>
        </div>
    )
}
