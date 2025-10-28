import { uuid } from 'lib/utils'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

import { Group } from '~/types'

type GroupFeedCanvas = {
    group: Group
}

const GroupFeedCanvas = ({ group }: GroupFeedCanvas): JSX.Element => {
    const groupKey = group.group_key

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
                            groupTypeIndex: group.group_type_index,
                            nodeId: uuid(),
                            children: [
                                {
                                    type: 'ph-group',
                                    attrs: {
                                        id: groupKey,
                                        groupTypeIndex: group.group_type_index,
                                        nodeId: uuid(),
                                        title: 'Info',
                                    },
                                },
                                {
                                    type: 'ph-group-properties',
                                    attrs: {
                                        groupKey,
                                        groupTypeIndex: group.group_type_index,
                                        nodeId: uuid(),
                                    },
                                },
                                {
                                    type: 'ph-related-groups',
                                    attrs: {
                                        id: groupKey,
                                        groupTypeIndex: group.group_type_index,
                                        nodeId: uuid(),
                                        title: 'Related people',
                                        type: 'person',
                                    },
                                },
                            ],
                        },
                    },
                ],
            }}
        />
    )
}

export default GroupFeedCanvas
