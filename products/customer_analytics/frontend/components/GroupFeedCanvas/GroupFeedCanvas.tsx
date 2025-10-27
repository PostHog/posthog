import { uuid } from 'lib/utils'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

import { Group } from '~/types'

type GroupFeedCanvas = {
    group: Group
}

const GroupFeedCanvas = ({ group }: GroupFeedCanvas): JSX.Element => {
    const key = group.group_key

    return (
        <Notebook
            editable={false}
            shortId={`canvas-${key}`}
            mode="canvas"
            initialContent={{
                type: 'doc',
                content: [
                    {
                        type: 'ph-usage-metrics',
                        attrs: {
                            groupKey: key,
                            groupTypeIndex: group.group_type_index,
                            nodeId: uuid(),
                            children: [
                                {
                                    type: 'ph-group',
                                    attrs: {
                                        id: key,
                                        groupTypeIndex: group.group_type_index,
                                        nodeId: uuid(),
                                        title: 'Info',
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
