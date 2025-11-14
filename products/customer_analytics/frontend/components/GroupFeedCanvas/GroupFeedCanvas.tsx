import { uuid } from 'lib/utils'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

import { Group } from '~/types'

type GroupFeedCanvas = {
    group: Group
}

const GroupFeedCanvas = ({ group }: GroupFeedCanvas): JSX.Element => {
    const groupKey = group.group_key
    const groupTypeIndex = group.group_type_index

    return (
        <Notebook
            editable={false}
            shortId={`canvas-${groupKey}`}
            mode="canvas"
            initialContent={{
                type: 'doc',
                content: [
                    {
                        type: 'ph-usage-metrics',
                        attrs: {
                            groupKey,
                            groupTypeIndex,
                            nodeId: uuid(),
                            children: [
                                {
                                    type: 'ph-group',
                                    attrs: {
                                        id: groupKey,
                                        groupTypeIndex,
                                        nodeId: uuid(),
                                        title: 'Info',
                                    },
                                },
                                {
                                    type: 'ph-group-properties',
                                    attrs: {
                                        groupKey,
                                        groupTypeIndex,
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
                        attrs: { groupKey, groupTypeIndex, nodeId: uuid() },
                    },
                    {
                        type: 'ph-llm-trace',
                        attrs: {
                            groupKey,
                            groupTypeIndex,
                            nodeId: uuid(),
                        },
                    },
                ],
            }}
        />
    )
}

export default GroupFeedCanvas
