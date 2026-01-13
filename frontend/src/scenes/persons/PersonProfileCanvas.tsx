import { BindLogic, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { AnyPropertyFilter, CustomerProfileScope, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

import { CustomerProfileMenu } from 'products/customer_analytics/frontend/components/CustomerProfileMenu'
import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

type PersonProfileCanvasProps = {
    person: PersonType
}

const PersonProfileCanvas = ({ person }: PersonProfileCanvasProps): JSX.Element | null => {
    const id = person.id
    const distinctId = person.distinct_ids[0]
    const shortId = `canvas-${id}`
    const mode = 'canvas'
    const { reportPersonProfileViewed } = useActions(eventUsageLogic)

    const attrs = useMemo(
        () => ({
            personId: id,
            distinctId,
        }),
        [id, distinctId]
    )
    const customerProfileLogicProps = {
        attrs,
        scope: CustomerProfileScope.PERSON,
        key: `person-${id}`,
        canvasShortId: shortId,
    }
    const { content } = useValues(customerProfileLogic(customerProfileLogicProps))

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
            <BindLogic logic={customerProfileLogic} props={customerProfileLogicProps}>
                <div className="flex items-start">
                    <CustomerProfileMenu />
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
