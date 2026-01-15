import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrending } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { formatCurrency } from 'lib/utils/geography/currency'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { groupLogic } from 'scenes/groups/groupLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { Group, PropertyFilterType, PropertyOperator } from '~/types'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'
import { calculateMRRData, getLifetimeValue, getPaidProducts } from './utils'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeGroupAttributes>): JSX.Element => {
    const { id, groupTypeIndex, tabId, title } = attributes
    const { groupData, groupDataLoading, groupTypeName } = useValues(
        groupLogic({
            groupKey: id,
            groupTypeIndex,
            tabId,
        })
    )
    const { setActions, insertAfter, setTitlePlaceholder } = useActions(notebookNodeLogic)

    const groupDisplay = groupData ? groupDisplayId(groupData.group_key, groupData.group_properties) : 'Group'
    const inGroupFeed = title === 'Info'

    useEffect(() => {
        const title = groupData ? `${groupTypeName}: ${groupDisplay}` : 'Group'
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

                        <GroupInfo groupData={groupData} />
                    </>
                ) : null}
            </div>
        </div>
    )
}

export function GroupInfo({ groupData }: { groupData: Group }): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const lifetimeValue = getLifetimeValue(groupData)

    return (
        <div className="flex flex-col">
            <div>
                <span className="text-secondary">First seen:</span>{' '}
                {groupData.created_at ? <TZLabel time={groupData.created_at} /> : 'unknown'}
            </div>
            <MRR groupData={groupData} />
            {lifetimeValue !== null && (
                <div>
                    <Tooltip title="Total worth of revenue from this customer over the whole relationship">
                        <span className="text-secondary">Lifetime value: </span>{' '}
                    </Tooltip>
                    {formatCurrency(lifetimeValue, baseCurrency)}
                </div>
            )}
            <PaidProducts groupData={groupData} />
        </div>
    )
}

export function MRR({ groupData }: { groupData: Group }): JSX.Element | null {
    const { baseCurrency } = useValues(teamLogic)
    const mrrData = calculateMRRData(groupData, baseCurrency)

    if (!mrrData) {
        return null
    }

    const icon =
        mrrData.trendDirection === 'up' ? (
            <IconTrending className="text-success" />
        ) : mrrData.trendDirection === 'down' ? (
            <IconTrendingDown className="text-danger" />
        ) : mrrData.trendDirection === 'flat' ? (
            <IconTrendingFlat />
        ) : null

    return (
        <div>
            <div className="flex gap-1 items-center">
                <span className="text-secondary">MRR:</span>
                <Tooltip title={mrrData.tooltipText}>
                    <div className="flex gap-2 items-center">
                        {formatCurrency(mrrData.mrr, baseCurrency)}
                        {icon}
                    </div>
                </Tooltip>
            </div>
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
    tabId?: string
    placement?: string
}

export const NotebookNodeGroup = createPostHogWidgetNode<NotebookNodeGroupAttributes>({
    nodeType: NotebookNodeType.Group,
    titlePlaceholder: 'Group',
    Component,
    heightEstimate: 300,
    minHeight: 100,
    href: (attrs) => urls.group(attrs.groupTypeIndex, attrs.id),
    resizeable: false,
    expandable: false,
    attributes: {
        id: {},
        groupTypeIndex: {},
        tabId: {},
        placement: {},
    },
    pasteOptions: {
        find: urls.group('([0-9]+)', '([^/]+)', false),
        getAttributes: async (match) => {
            return { groupTypeIndex: parseInt(match[1]), id: decodeURIComponent(match[2]) }
        },
    },
    serializedText: (attrs) => {
        const title = attrs?.title || ''
        const id = attrs?.id || ''
        return `${title} ${id}`.trim()
    },
})
