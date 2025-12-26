import { BindLogic, useActions } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { uuid } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { AnyPropertyFilter, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

type PersonFeedCanvasProps = {
    person: PersonType
}

const PersonFeedCanvas = ({ person }: PersonFeedCanvasProps): JSX.Element => {
    const { reportPersonProfileViewed } = useActions(eventUsageLogic)
    const id = person.id
    const distinctId = person.distinct_ids[0]
    const shortId = `canvas-${id}`
    const mode = 'canvas'

    const personFilter: AnyPropertyFilter[] = [
        {
            type: PropertyFilterType.EventMetadata,
            key: 'person_id',
            value: id,
            operator: PropertyOperator.Exact,
        },
    ]

    useOnMountEffect(() => {
        reportPersonProfileViewed()
    })

    return (
        <BindLogic logic={notebookLogic} props={{ shortId, mode, canvasFiltersOverride: personFilter }}>
            <Notebook
                editable={false}
                shortId={shortId}
                mode={mode}
                initialContent={{
                    type: 'doc',
                    content: [
                        { type: 'ph-usage-metrics', attrs: { personId: id, nodeId: uuid() } },
                        {
                            type: 'ph-person-feed',
                            attrs: {
                                height: null,
                                title: null,
                                nodeId: uuid(),
                                id,
                                distinctId,
                                __init: null,
                                children: [
                                    {
                                        type: 'ph-person',
                                        attrs: { id, distinctId, nodeId: uuid(), title: 'Info' },
                                    },
                                    // FIXME: Map bg image is broken
                                    // ...(isCloudOrDev
                                    //     ? [
                                    //           {
                                    //               type: 'ph-map',
                                    //               attrs: { id, distinctId, nodeId: uuid() },
                                    //           },
                                    //       ]
                                    //     : []),
                                    {
                                        type: 'ph-person-properties',
                                        attrs: { id, distinctId, nodeId: uuid() },
                                    },
                                    { type: 'ph-related-groups', attrs: { id, nodeId: uuid(), type: 'group' } },
                                ],
                            },
                        },
                        {
                            type: 'ph-llm-trace',
                            attrs: { personId: id, nodeId: uuid() },
                        },
                        {
                            type: 'ph-zendesk-tickets',
                            attrs: { personId: id, nodeId: uuid() },
                        },
                        {
                            type: 'ph-issues',
                            attrs: { personId: id, nodeId: uuid() },
                        },
                    ],
                }}
            />
        </BindLogic>
    )
}

export default PersonFeedCanvas
