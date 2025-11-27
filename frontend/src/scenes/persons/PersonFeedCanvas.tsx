import { useValues } from 'kea'

import { uuid } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

import { AnyPropertyFilter, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

type PersonFeedCanvasProps = {
    person: PersonType
}

const PersonFeedCanvas = ({ person }: PersonFeedCanvasProps): JSX.Element => {
    const { isCloudOrDev } = useValues(preflightLogic)

    const id = person.id
    const distinctId = person.distinct_ids[0]

    const personFilter: AnyPropertyFilter[] = [
        {
            type: PropertyFilterType.EventMetadata,
            key: 'person_id',
            value: id,
            operator: PropertyOperator.Exact,
        },
    ]

    return (
        <Notebook
            editable={false}
            shortId={`canvas-${id}`}
            mode="canvas"
            canvasFiltersOverride={personFilter}
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
                                ...(isCloudOrDev
                                    ? [
                                          {
                                              type: 'ph-map',
                                              attrs: { id, distinctId, nodeId: uuid() },
                                          },
                                      ]
                                    : []),
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
    )
}

export default PersonFeedCanvas
