import { BindLogic, useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { uuid } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { groupLogic } from 'scenes/groups/groupLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, Group, PropertyFilterType, PropertyOperator } from '~/types'

interface GroupFeedCanvasProps {
    group: Group
    tabId: string
}

export const GroupFeedCanvas = ({ group, tabId }: GroupFeedCanvasProps): JSX.Element => {
    const { aggregationLabel } = useValues(groupsModel)
    const { reportGroupProfileViewed } = useActions(eventUsageLogic)
    const groupKey = group.group_key
    const groupTypeIndex = group.group_type_index

    const shortId = `canvas-${groupKey}-${tabId}`
    const mode = 'canvas'

    const groupFilter: AnyPropertyFilter[] = [
        {
            type: PropertyFilterType.EventMetadata,
            key: `$group_${groupTypeIndex}`,
            label: aggregationLabel(groupTypeIndex).singular,
            value: groupKey,
            operator: PropertyOperator.Exact,
        },
    ]

    useOnMountEffect(() => {
        reportGroupProfileViewed()
    })

    return (
        <BindLogic logic={notebookLogic} props={{ shortId, mode, canvasFiltersOverride: groupFilter }}>
            <BindLogic logic={groupLogic} props={{ groupKey, groupTypeIndex, tabId }}>
                <Notebook
                    editable={false}
                    shortId={`canvas-${groupKey}-${tabId}`}
                    mode="canvas"
                    canvasFiltersOverride={groupFilter}
                    initialContent={{
                        type: 'doc',
                        content: [
                            {
                                type: 'ph-usage-metrics',
                                attrs: {
                                    groupKey,
                                    groupTypeIndex,
                                    tabId,
                                    nodeId: uuid(),
                                    children: [
                                        {
                                            type: 'ph-group',
                                            attrs: {
                                                id: groupKey,
                                                groupTypeIndex,
                                                tabId,
                                                nodeId: uuid(),
                                                title: 'Info',
                                            },
                                        },
                                        {
                                            type: 'ph-group-properties',
                                            attrs: {
                                                nodeId: uuid(),
                                            },
                                        },
                                        {
                                            type: 'ph-related-groups',
                                            attrs: {
                                                id: groupKey,
                                                groupTypeIndex,
                                                nodeId: uuid(),
                                                title: 'Related people',
                                                type: 'person',
                                            },
                                        },
                                    ],
                                },
                            },
                            {
                                type: 'ph-llm-trace',
                                attrs: {
                                    groupKey,
                                    groupTypeIndex,
                                    tabId,
                                    nodeId: uuid(),
                                },
                            },
                            {
                                type: 'ph-zendesk-tickets',
                                attrs: { groupKey, nodeId: uuid() },
                            },
                            {
                                type: 'ph-issues',
                                attrs: { groupKey, groupTypeIndex, tabId, nodeId: uuid() },
                            },
                        ],
                    }}
                />
            </BindLogic>
        </BindLogic>
    )
}
