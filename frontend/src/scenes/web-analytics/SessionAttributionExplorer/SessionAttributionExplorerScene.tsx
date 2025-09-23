import { useActions, useValues } from 'kea'
import React from 'react'

import { IconCollapse, IconExpand, IconPlus } from '@posthog/icons'
import { LemonMenu, LemonSwitch } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { Query } from '~/queries/Query/Query'
import { isSessionPropertyFilters } from '~/queries/schema-guards'
import { DataTableNode, HogQLQuery, SessionAttributionGroupBy } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'

import { sessionAttributionExplorerLogic } from './sessionAttributionExplorerLogic'

export function SessionAttributionExplorerScene(): JSX.Element {
    return <SessionAttributionExplorer />
}

export const scene: SceneExport = {
    component: SessionAttributionExplorerScene,
    logic: sessionAttributionExplorerLogic,
    settingSectionId: 'environment-web-analytics',
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
        ad_ids: {
            title: 'Ad IDs',
            render: ExpandableDataCell,
        },
        example_entry_urls: {
            title: 'Example entry URLs',
            render: ExpandableDataCell,
        },
    },
    emptyStateHeading: 'There are no matching sessions for this query',
    emptyStateDetail: 'Try changing the date range, or changing the property filters.',
}

const groupByOptions = [
    {
        label: 'Channel type',
        value: SessionAttributionGroupBy.ChannelType,
    },
    {
        label: 'Referring domain',
        value: SessionAttributionGroupBy.ReferringDomain,
    },
    {
        label: 'UTM source',
        value: SessionAttributionGroupBy.Source,
    },
    {
        label: 'UTM medium',
        value: SessionAttributionGroupBy.Medium,
    },
    {
        label: 'UTM campaign',
        value: SessionAttributionGroupBy.Campaign,
    },
    {
        label: 'Ad IDs',
        value: SessionAttributionGroupBy.AdIds,
    },
    {
        label: 'Entry URL',
        value: SessionAttributionGroupBy.InitialURL,
    },
]

export const GroupByFilter = (): JSX.Element => {
    const { groupBy } = useValues(sessionAttributionExplorerLogic)
    const { enableGroupBy, disableGroupBy } = useActions(sessionAttributionExplorerLogic)

    return (
        <div className="mb-2">
            <LemonMenu
                items={groupByOptions.map(({ label, value }) => {
                    return {
                        label: () => (
                            <LemonSwitch
                                checked={groupBy.includes(value)}
                                onChange={(val) => {
                                    if (val) {
                                        enableGroupBy(value)
                                    } else {
                                        disableGroupBy(value)
                                    }
                                }}
                                fullWidth={true}
                                label={label}
                            />
                        ),
                    }
                })}
                closeOnClickInside={false}
            >
                <LemonButton icon={<IconPlus />} size="small" type="secondary">
                    Group by
                </LemonButton>
            </LemonMenu>
        </div>
    )
}

export function SessionAttributionExplorer(): JSX.Element {
    const { query } = useValues(sessionAttributionExplorerLogic)
    const { setDateRange, setProperties } = useActions(sessionAttributionExplorerLogic)
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    const showSupportOptions = preflight?.cloud
    return (
        <div>
            <SceneBreadcrumbBackButton />
            <LemonBanner type="info" className="my-4">
                <div className="flex items-center flex-wrap gap-2 justify-between">
                    <div className="flex-1 min-w-full sm:min-w-0">
                        <p>
                            You can use the Session attribution explorer (beta) to understand how your sessions are
                            attributed. We use the referring domain, <code>utm_source</code>, <code>utm_medium</code>,{' '}
                            <code>utm_campaign</code>, and the presence of advertising ids like <code>gclid</code> and{' '}
                            <code>gad_source</code>, to assign a session a{' '}
                            <Link to="https://posthog.com/docs/data/channel-type">Channel type</Link>.
                        </p>
                        <p>
                            If you believe that a session is attributed incorrectly, please let us know! If you'd like
                            to customize your Channel attribution, please leave feedback on the{' '}
                            <Link to="https://github.com/PostHog/posthog/issues/21195">feature request</Link>.
                        </p>
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
            <GroupByFilter />
            <Query<DataTableNode>
                context={queryContext}
                query={query}
                setQuery={(query) => {
                    const source = query.source as HogQLQuery
                    if (source.filters && isSessionPropertyFilters(source.filters.properties)) {
                        setProperties(source.filters.properties)
                    } else {
                        setProperties([])
                    }
                    setDateRange(source.filters?.dateRange ?? null)
                }}
            />
        </div>
    )
}
