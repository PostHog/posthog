import { IconCollapse, IconExpand } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import React from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, HogQLQuery } from '~/queries/schema'
import { isSessionPropertyFilters } from '~/queries/schema-guards'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'

import { sessionAttributionExplorerLogic } from './sessionAttributionExplorerLogic'

export function SessionAttributionExplorerScene(): JSX.Element {
    return <SessionAttributionExplorer />
}

export const scene: SceneExport = {
    component: SessionAttributionExplorerScene,
    logic: sessionAttributionExplorerLogic,
}

const ExpandableDataCell: QueryContextColumnComponent = ({ value }: { value: unknown }): JSX.Element => {
    const [isExpanded, setIsExpanded] = React.useState(false)

    if (value == null || (Array.isArray(value) && value.length === 0)) {
        return (
            <Tooltip title="NULL">
                <span aria-hidden={true} className="cursor-default">
                    —
                </span>
            </Tooltip>
        )
    }

    if (!Array.isArray(value)) {
        return <div>{value}</div>
    }

    return (
        <div className="flex flex-row">
            <div>
                <span>
                    <LemonButton
                        active={isExpanded}
                        onClick={() => {
                            setIsExpanded(!isExpanded)
                        }}
                        icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                        title={isExpanded ? 'Show less' : 'Show more'}
                        size="small"
                    />
                </span>
            </div>
            <div className="flex flex-col items-center justify-center">
                <div className="flex flex-1">
                    {isExpanded ? (
                        <ul className="flex-1 flex flex-col">
                            {value.map((url) => (
                                <li className="flex-1 mb-1 break-all" key={url}>
                                    {url}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        value[0]
                    )}
                </div>
            </div>
        </div>
    )
}

const queryContext: QueryContext = {
    columns: {
        channel_type: {
            title: 'Channel type',
            render: ExpandableDataCell,
        },
        count: {
            title: 'Session count',
            align: 'right',
        },
        referring_domain: {
            title: 'Referring domain',
            render: ExpandableDataCell,
        },
        utm_source: {
            title: 'UTM source',
            render: ExpandableDataCell,
        },
        utm_medium: {
            title: 'UTM medium',
            render: ExpandableDataCell,
        },
        utm_campaign: {
            title: 'UTM campaign',
            render: ExpandableDataCell,
        },
        has_ad_id: {
            title: 'Ad IDs',
            render: ExpandableDataCell,
        },
        example_entry_urls: {
            title: 'Example entry URLs',
            render: ExpandableDataCell,
        },
    },
}

export function SessionAttributionExplorer(): JSX.Element {
    const { query } = useValues(sessionAttributionExplorerLogic)
    const { setDateRange, setProperties } = useActions(sessionAttributionExplorerLogic)
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    const showSupportOptions = preflight?.cloud
    return (
        <div>
            <LemonBanner type="info" className="my-4">
                <div className="flex items-center flex-wrap gap-2 justify-between">
                    <div className="flex-1 min-w-full sm:min-w-0">
                        <p>
                            You can use the Session attribution explorer (beta) to find understand how your sessions are
                            attributed. We use the referring domain, <code>utm_source</code>, <code>utm_medium</code>,{' '}
                            <code>utm_campaign</code>, and the presence of advertising ids like <code>gclid</code> and{' '}
                            <code>gad_source</code>, to assign a session a{' '}
                            <Link to="https://posthog.com/docs/data/channel-type">Channel type</Link>.
                        </p>
                        <p>
                            The table below groups sessions with the same value for Channel type, referring domain,
                            source, medium, and which ad ids are present. It shows the count of sessions in each group,
                            and some example entry URLs from that group.
                        </p>
                        <p>If you believe that a session is attributed incorrectly, please let us know!</p>
                    </div>
                    {showSupportOptions ? (
                        <span className="flex items-center gap-2">
                            <LemonButton
                                type="secondary"
                                icon={<IconFeedback />}
                                onClick={() =>
                                    openSupportForm({
                                        kind: 'feedback',
                                        isEmailFormOpen: true,
                                        target_area: 'web_analytics',
                                    })
                                }
                            >
                                Give feedback
                            </LemonButton>
                        </span>
                    ) : null}
                </div>
            </LemonBanner>
            <Query<DataTableNode>
                context={queryContext}
                query={query}
                setQuery={(query) => {
                    const source = query.source as HogQLQuery
                    if (source.filters?.properties && isSessionPropertyFilters(source.filters.properties)) {
                        setProperties(source.filters.properties)
                    }
                    if (source.filters?.dateRange) {
                        setDateRange(source.filters.dateRange)
                    }
                }}
            />
        </div>
    )
}
