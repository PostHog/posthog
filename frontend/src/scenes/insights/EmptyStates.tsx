import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import imgEmptyLineGraph from 'public/empty-line-graph.svg'
import imgEmptyLineGraphDark from 'public/empty-line-graph-dark.svg'
import { QuestionCircleOutlined, LoadingOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { IllustrationDanger } from 'lib/components/icons'

export function LineGraphEmptyState({ color }: { color: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <>
            {!featureFlags['1694-dashboards'] && (
                <p style={{ textAlign: 'center', paddingTop: '4rem' }}>
                    We couldn't find any matching events. Try changing dates or pick another action or event.
                </p>
            )}
            {featureFlags['1694-dashboards'] && (
                <div className="text-center" style={{ height: '100%' }}>
                    <img
                        src={color === 'white' ? imgEmptyLineGraphDark : imgEmptyLineGraph}
                        alt=""
                        style={{ maxHeight: '100%', maxWidth: '80%', opacity: 0.5 }}
                    />
                    <div style={{ textAlign: 'center', fontWeight: 'bold', marginTop: 16 }}>
                        Seems like there's no data to show this graph yet{' '}
                        <a
                            target="_blank"
                            href="https://posthog.com/docs/features/trends"
                            style={{ color: color === 'white' ? 'rgba(0, 0, 0, 0.85)' : 'white' }}
                        >
                            <QuestionCircleOutlined />
                        </a>
                    </div>
                </div>
            )}
        </>
    )
}

export function TimeOut({ isLoading }: { isLoading: boolean }): JSX.Element {
    const { user } = useValues(userLogic)
    return (
        <div className="insight-empty-state timeout-message">
            <div className="illustration-main">{isLoading ? <LoadingOutlined spin /> : <IllustrationDanger />}</div>

            <h3 className="l3">
                {isLoading ? <>Looks like things are a little slow...</> : <>Your query took too long to complete. </>}
            </h3>
            {isLoading ? (
                <>
                    Your query is taking a long time to complete. <b>We're still working on it.</b> However, here are
                    some things you can try to speed it up:
                </>
            ) : (
                <>
                    Here are some things you can try to speed up your query and <b>try again</b>:
                </>
            )}
            <ol>
                <li>Reduce the date range of your query</li>
                <li>Remove some filters</li>
                {!user?.is_multi_tenancy && <li>Increase the size of your database server</li>}
                {!user?.is_multi_tenancy && !user?.ee_enabled && (
                    <li>
                        <a
                            data-attr="insight-timeout-upgrade-to-clickhouse"
                            href="https://posthog.com/pricing?o=enterprise&utm_medium=in-product&utm_campaign=insight-timeout-empty-state"
                            rel="noopener"
                            target="_blank"
                        >
                            Upgrade PostHog
                        </a>{' '}
                        to enterprise to get access to Clickhouse
                    </li>
                )}
                <li>
                    <a
                        data-attr="insight-timeout-raise-issue"
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
    )
}

export function ErrorMessage(): JSX.Element {
    return (
        <div className="insight-empty-state error-message">
            <div className="illustration-main">
                <IllustrationDanger />
            </div>
            <h3 className="l3">There was an error completing this query</h3>
            <div className="mt">
                We apologize for this unexpected situation. There are a few things you can do:
                <ol>
                    <li>
                        First and foremost you can <b>try again</b>. We recommended you wait a few moments before doing
                        so.
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
        </div>
    )
}
