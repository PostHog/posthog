import { BindLogic, useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { AnyPropertyFilter, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

import { personProfileCanvasLogic } from 'products/customer_analytics/frontend/personProfileCanvasLogic'

type PersonProfileCanvasProps = {
    person: PersonType
}

const PersonProfileCanvas = ({ person }: PersonProfileCanvasProps): JSX.Element => {
    const id = person.id
    const distinctId = person.distinct_ids[0]
    const { reportPersonProfileViewed } = useActions(eventUsageLogic)
    const { content } = useValues(personProfileCanvasLogic({ personId: id, distinctId }))
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
                    content,
                }}
            />
        </BindLogic>
    )
}

export default PersonProfileCanvas
