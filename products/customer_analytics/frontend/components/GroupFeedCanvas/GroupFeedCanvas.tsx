import { BindLogic } from 'kea'

import { uuid } from 'lib/utils'
import { groupLogic } from 'scenes/groups/groupLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

import { Group } from '~/types'

interface GroupFeedCanvasProps {
    group: Group
    tabId: string
}

export const GroupFeedCanvas = ({ group, tabId }: GroupFeedCanvasProps): JSX.Element => {
    const groupKey = group.group_key
    const groupTypeIndex = group.group_type_index

    return (
        <BindLogic logic={groupLogic} props={{ groupKey, groupTypeIndex, tabId }}>
            <Notebook
                editable={false}
                shortId={`canvas-${groupKey}-${tabId}`}
                mode="canvas"
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
                            type: 'ph-issues',
                            attrs: { groupKey, groupTypeIndex, tabId, nodeId: uuid() },
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
                    ],
                }}
            />
        </BindLogic>
    )
}
