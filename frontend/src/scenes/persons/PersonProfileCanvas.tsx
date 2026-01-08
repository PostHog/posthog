import { BindLogic, useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { AnyPropertyFilter, CustomerProfileScope, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

import { CustomerProfileMenu } from 'products/customer_analytics/frontend/components/CustomerProfileMenu'
import { personProfileLogic } from 'products/customer_analytics/frontend/personProfileLogic'

type PersonProfileCanvasProps = {
    person: PersonType
}

const PersonProfileCanvas = ({ person }: PersonProfileCanvasProps): JSX.Element | null => {
    const id = person.id
    const distinctId = person.distinct_ids[0]
    const { reportPersonProfileViewed } = useActions(eventUsageLogic)
    const { content } = useValues(personProfileLogic({ personId: id, distinctId }))
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
            <BindLogic logic={personProfileLogic} props={{ personId: id, distinctId }}>
                <div className="flex items-start">
                    <CustomerProfileMenu scope={CustomerProfileScope.PERSON} content={content} />
                </div>
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
        </BindLogic>
    )
}

export default PersonProfileCanvas
