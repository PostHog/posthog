import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { GroupCaption } from 'scenes/groups/Group'
import { groupLogic } from 'scenes/groups/groupLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeGroupAttributes>): JSX.Element => {
    const { id, groupTypeIndex } = attributes

    const logic = groupLogic({ groupKey: id, groupTypeIndex: groupTypeIndex })
    const { groupData, groupDataLoading, groupTypeName } = useValues(logic)
    const { setActions, insertAfter, setTitlePlaceholder } = useActions(notebookNodeLogic)

    const groupDisplay = groupData ? groupDisplayId(groupData.group_key, groupData.group_properties) : 'Group'

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
            <div className={clsx('p-4 flex-0 flex gap-2 justify-between flex-wrap')}>
                {groupDataLoading ? (
                    <LemonSkeleton className="h-6" />
                ) : groupData ? (
                    <>
                        <div className="flex-1 font-semibold truncate">{groupDisplay}</div>
                        <GroupCaption groupData={groupData} groupTypeName={groupTypeName} />
                    </>
                ) : null}
            </div>
        </div>
    )
}

type NotebookNodeGroupAttributes = {
    id: string
    groupTypeIndex: number
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
    },
    pasteOptions: {
        find: urls.groups('(.+)'),
        getAttributes: async (match) => {
            const [groupTypeIndex, id] = match[1].split('/')
            return { id: decodeURIComponent(id), groupTypeIndex: parseInt(groupTypeIndex) }
        },
    },
    serializedText: (attrs) => {
        const title = attrs?.title || ''
        const id = attrs?.id || ''
        return `${title} ${id}`.trim()
    },
})
