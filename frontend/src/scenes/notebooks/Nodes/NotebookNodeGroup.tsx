import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrending } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { formatCurrency } from 'lib/utils/currency'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { groupLogic } from 'scenes/groups/groupLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { defineNotebookWidgetViews, getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { CurrencyCode, NodeKind } from '~/queries/schema/schema-general'
import { Group, PropertyFilterType, PropertyOperator } from '~/types'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { DataSourceIcon } from './components/DataSourceIcon'
import { notebookNodeLogic } from './notebookNodeLogic'
import { calculateMRRData, getPaidProducts } from './utils'

const Component = (props: NotebookNodeProps<NotebookNodeGroupAttributes>): JSX.Element => {
    return <GroupCard {...props} compact={false} />
}

function GroupCard({
    attributes,
    compact,
}: NotebookNodeProps<NotebookNodeGroupAttributes> & { compact: boolean }): JSX.Element {
    const { id, groupTypeIndex, tabId, title } = attributes
    const mountedGroupLogic = groupLogic({
        groupKey: id,
        groupTypeIndex,
        tabId,
    })
    const { groupData, groupDataLoading, groupRevenueAnalyticsDataLoading, effectiveMRR, effectiveLifetimeValue } =
        useValues(mountedGroupLogic)
    const { setActions, insertAfter, setTitlePlaceholder } = useActions(notebookNodeLogic)
    const { notebookLogic } = useValues(notebookNodeLogic)
    useAttachedLogic(mountedGroupLogic, notebookLogic)

    const groupDisplay = groupData ? groupDisplayId(groupData.group_key, groupData.group_properties) : 'Group'
    const inGroupFeed = title === 'Info'

    useEffect(() => {
        const title = groupData ? groupDisplay : 'Group'
        setTitlePlaceholder(title)
        setActions([
            {
                text: 'Events for this group',
                onClick: () => {
                    insertAfter({
                        type: NotebookNodeType.Query,
                        attrs: {
                            title: `Events for ${title}`,
                            query: {
                                kind: NodeKind.DataTableNode,
                                full: true,
                                source: {
                                    kind: NodeKind.EventsQuery,
                                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                                    after: '-24h',
                                    properties: [
                                        {
                                            key: `$group_${groupTypeIndex}`,
                                            value: id,
                                            type: PropertyFilterType.Event,
                                            operator: PropertyOperator.Exact,
                                        },
                                    ],
                                },
                            },
                        },
                    })
                },
            },
        ])
        // oxlint-disable-next-line exhaustive-deps
    }, [groupData])

    if (!groupData && !groupDataLoading) {
        return <NotFound object="group" />
    }

    return (
        <div className="flex flex-col overflow-hidden">
            <div className={`p-4 flex-0 flex gap-2 justify-between ${inGroupFeed ? 'flex-col' : 'flex-wrap'}`}>
                {groupDataLoading ? (
                    <div className={`flex flex-1 gap-2 ${inGroupFeed ? 'flex-col' : 'flex-wrap'}`}>
                        <LemonSkeleton className="h-4 w-20 mb-2" />
                        <LemonSkeleton className="h-3 w-32" />
                        <LemonSkeleton className="h-3 w-40" />
                        <LemonSkeleton className="h-3 w-44" />
                    </div>
                ) : groupData ? (
                    <>
                        <div>
                            <div className="flex-1 font-semibold truncate">{groupDisplay}</div>
                            <CopyToClipboardInline
                                explicitValue={id}
                                iconStyle={{ color: 'var(--color-accent)' }}
                                description="group key"
                                className="text-xs text-muted"
                            >
                                {stringWithWBR(id, 40)}
                            </CopyToClipboardInline>
                        </div>

                        {!compact ? (
                            <GroupInfo
                                groupData={groupData}
                                mrr={effectiveMRR}
                                lifetimeValue={effectiveLifetimeValue}
                                isMRRLoading={groupRevenueAnalyticsDataLoading}
                                isLifetimeValueLoading={groupRevenueAnalyticsDataLoading}
                            />
                        ) : null}
                    </>
                ) : null}
            </div>
        </div>
    )
}

interface GroupInfoProps {
    groupData: Group
    mrr: { value: number | null; source: 'revenue-analytics' | 'properties' | null }
    lifetimeValue: { value: number | null; source: 'revenue-analytics' | 'properties' | null }
    isMRRLoading: boolean
    isLifetimeValueLoading: boolean
}

export function GroupInfo({
    groupData,
    mrr,
    lifetimeValue,
    isMRRLoading,
    isLifetimeValueLoading,
}: GroupInfoProps): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)

    return (
        <div className="flex flex-col">
            <div>
                <span className="text-secondary">First seen:</span>{' '}
                {groupData.created_at ? <TZLabel time={groupData.created_at} /> : 'unknown'}
            </div>
            <MRR groupData={groupData} mrr={mrr} baseCurrency={baseCurrency} isLoading={isMRRLoading} />
            <LifetimeValue
                lifetimeValue={lifetimeValue}
                baseCurrency={baseCurrency}
                isLoading={isLifetimeValueLoading}
            />
            <PaidProducts groupData={groupData} />
        </div>
    )
}

export function MRR({
    groupData,
    mrr,
    baseCurrency,
    isLoading,
}: {
    groupData: Group
    mrr: { value: number | null; source: 'revenue-analytics' | 'properties' | null }
    baseCurrency: CurrencyCode
    isLoading: boolean
}): JSX.Element | null {
    if (isLoading) {
        return (
            <div className="flex gap-1 items-center">
                <LemonSkeleton className="h-4 w-32" />
            </div>
        )
    }

    // Calculate MRR data with trend (if from properties)
    const mrrData =
        mrr.source === 'properties'
            ? calculateMRRData(groupData, baseCurrency)
            : mrr.value !== null
              ? {
                    mrr: mrr.value,
                    forecastedMrr: null,
                    percentageDiff: null,
                    tooltipText: null,
                    trendDirection: null,
                }
              : null

    if (!mrrData) {
        return null
    }

    const icon =
        mrrData.trendDirection === 'up' ? (
            <IconTrending data-attr="trending-icon" className="text-success" />
        ) : mrrData.trendDirection === 'down' ? (
            <IconTrendingDown className="text-danger" />
        ) : mrrData.trendDirection === 'flat' ? (
            <IconTrendingFlat />
        ) : null

    return (
        <div className="flex gap-1 items-center">
            <span className="text-secondary">MRR:</span>
            <div className="flex gap-2 items-center">
                <Tooltip title={mrrData.tooltipText}>
                    <div className="flex gap-1 items-center">
                        {formatCurrency(mrrData.mrr, baseCurrency)}
                        {icon}
                    </div>
                </Tooltip>
                <DataSourceIcon source={mrr.source} />
            </div>
        </div>
    )
}

export function LifetimeValue({
    lifetimeValue,
    baseCurrency,
    isLoading,
}: {
    lifetimeValue: { value: number | null; source: 'revenue-analytics' | 'properties' | null }
    baseCurrency: CurrencyCode
    isLoading: boolean
}): JSX.Element | null {
    if (isLoading) {
        return (
            <div className="flex items-center gap-1">
                <LemonSkeleton className="h-4 w-40" />
            </div>
        )
    }

    if (lifetimeValue.value === null) {
        return null
    }

    return (
        <div className="flex items-center gap-1">
            <Tooltip title="Total worth of revenue from this customer over the whole relationship">
                <span className="text-secondary">Lifetime value: </span>{' '}
            </Tooltip>
            {formatCurrency(lifetimeValue.value, baseCurrency)}
            <DataSourceIcon source={lifetimeValue.source} />
        </div>
    )
}

export function PaidProducts({ groupData }: { groupData: Group }): JSX.Element | null {
    const paidProducts = getPaidProducts(groupData)

    if (paidProducts.length === 0) {
        return null
    }

    const paidProductTags = paidProducts.map((product) => (
        <LemonTag className="mr-1 mb-1" key={product} children={product} />
    ))

    return <div>Paid products: {paidProductTags}</div>
}

type NotebookNodeGroupAttributes = {
    id: string
    groupTypeIndex: number
    view?: string
    tabId?: string
    placement?: string
}

function GroupSummary(props: NotebookNodeProps<NotebookNodeGroupAttributes>): JSX.Element {
    return <GroupCard {...props} compact />
}

function GroupActivity({ attributes }: NotebookNodeProps<NotebookNodeGroupAttributes>): JSX.Element {
    const { notebookLogic } = useValues(notebookNodeLogic)
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)
    const { groupData } = useValues(
        groupLogic({
            groupKey: attributes.id,
            groupTypeIndex: attributes.groupTypeIndex,
            tabId: attributes.tabId,
        })
    )

    useEffect(() => {
        setTitlePlaceholder(groupData ? groupDisplayId(groupData.group_key, groupData.group_properties) : 'Group')
    }, [groupData, setTitlePlaceholder])

    return (
        <Query
            uniqueKey={`${attributes.nodeId}-activity`}
            attachTo={notebookLogic}
            query={{
                kind: NodeKind.DataTableNode,
                embedded: true,
                full: false,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                    after: '-30d',
                    limit: 50,
                    fixedProperties: [
                        {
                            key: `$group_${attributes.groupTypeIndex}`,
                            value: attributes.id,
                            type: PropertyFilterType.Event,
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            }}
            readOnly
        />
    )
}

const GROUP_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<NotebookNodeGroupAttributes, 'Group'>('Group', {
    summary: GroupSummary,
    activity: GroupActivity,
})

export const NotebookNodeGroup = createPostHogWidgetNode<NotebookNodeGroupAttributes>({
    nodeType: NotebookNodeType.Group,
    titlePlaceholder: 'Group',
    editableTitle: false,
    Component,
    heightEstimate: 300,
    minHeight: 100,
    href: (attrs) => urls.group(attrs.groupTypeIndex, attrs.id),
    resizeable: false,
    expandable: false,
    attributes: {
        id: {},
        groupTypeIndex: {},
        view: {},
        tabId: {},
        placement: {},
    },
    defaultView: getNotebookWidgetDefaultView('Group'),
    views: GROUP_NOTEBOOK_WIDGET_VIEWS,
    serializedText: (attrs) => attrs.title || 'Group',
})
