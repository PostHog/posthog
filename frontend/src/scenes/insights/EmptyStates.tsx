import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import imgEmptyLineGraph from 'public/empty-line-graph.svg'
import imgEmptyLineGraphDark from 'public/empty-line-graph-dark.svg'
import { QuestionCircleOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

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

export function TimeOut(): JSX.Element {
    const { user } = useValues(userLogic)
    return (
        <div style={{}}>
            <h2>Looks like things are a little slow</h2>
            Your query is taking a long time to complete. Here are some things you can try:
            <ol>
                <li>Reduce the date range of your query</li>
                <li>Remove some filters</li>
                {!user?.is_multi_tenancy && <li>Increase the size of your database</li>}
                {!user?.is_multi_tenancy && user?.ee_enabled && (
                    <li>
                        <a
                            data-attr="insight-timeout-upgrade-to-clickhouse"
                            href="https://posthog.com/pricing?o=enterprise"
                            rel="noopener noreferrer"
                            target="_blank"
                        >
                            Upgrade your database to Clickhouse
                        </a>
                    </li>
                )}
                <li>
                    <a data-attr="insight-timeout-raise-issue" href="https://github.com/PostHog/posthog.com/issues/new">
                        Raise an issue in our repo
                    </a>
                </li>
                <li>
                    Get in touch with us{' '}
                    <a
                        data-attr="insight-timeout-slack"
                        href="https://posthog.com/slack"
                        rel="noopener noreferrer"
                        target="_blank"
                    >
                        on slack
                    </a>
                </li>
                <li>
                    Email us{' '}
                    <a data-attr="insight-timeout-email" href="mailto:hey@posthog.com">
                        hey@posthog.com
                    </a>
                </li>
            </ol>
        </div>
    )
}

export function ErrorMessage(): JSX.Element {
    return (
        <div style={{}}>
            <h2>There was an error while completing this query</h2>
            Please try again later or:
            <ol>
                <li>
                    <a data-attr="insight-error-raise-issue" href="https://github.com/PostHog/posthog.com/issues/new">
                        Raise an issue in our repo
                    </a>
                </li>
                <li>
                    Get in touch with us{' '}
                    <a
                        data-attr="insight-error-slack"
                        href="https://posthog.com/slack"
                        rel="noopener noreferrer"
                        target="_blank"
                    >
                        on slack
                    </a>
                </li>
                <li>
                    Email us{' '}
                    <a data-attr="insight-error-email" href="mailto:hey@posthog.com">
                        hey@posthog.com
                    </a>
                </li>
            </ol>
        </div>
    )
}
