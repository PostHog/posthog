import { useValues } from 'kea'

import { PersonType } from '~/types'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { uuid } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

type PersonFeedCanvasProps = {
    person: PersonType
}

const PersonFeedCanvas = ({ person }: PersonFeedCanvasProps): JSX.Element => {
    const { isCloudOrDev } = useValues(preflightLogic)

    const id = person.id

    const personId = person.distinct_ids[0]

    return (
        <Notebook
            editable={false}
            shortId={`canvas-${id}`}
            mode="canvas"
            initialContent={{
                type: 'doc',
                content: [
                    {
                        type: 'ph-person-feed',
                        attrs: {
                            height: null,
                            title: null,
                            nodeId: uuid(),
                            id: personId,
                            __init: null,
                            children: [
                                {
                                    type: 'ph-person',
                                    attrs: { id: personId, nodeId: uuid(), title: 'Info' },
                                },
                                ...(isCloudOrDev
                                    ? [
                                          {
                                              type: 'ph-map',
                                              attrs: { id: personId, nodeId: uuid() },
                                          },
                                      ]
                                    : []),
                                {
                                    type: 'ph-properties',
                                    attrs: { id: personId, nodeId: uuid() },
                                },
                            ],
                        },
                    },
                ],
            }}
        />
    )
}

export default PersonFeedCanvas
