import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { GroupCaption } from 'scenes/groups/components/GroupCaption'
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
    const { id, groupTypeIndex, title } = attributes

    const logic = groupLogic({ groupKey: id, groupTypeIndex: groupTypeIndex })
    const { groupData, groupDataLoading, groupTypeName } = useValues(logic)
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
                        <div className="flex-1 font-semibold truncate">{groupDisplay}</div>
                        <GroupCaption
                            groupData={groupData}
                            groupTypeName={groupTypeName}
                            displayType={inGroupFeed ? 'col' : 'wrap'}
                        />
                    </>
                ) : null}
            </div>
        </div>
    )
}

type NotebookNodeGroupAttributes = {
    id: string
    groupTypeIndex: number
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
        placement: {},
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
