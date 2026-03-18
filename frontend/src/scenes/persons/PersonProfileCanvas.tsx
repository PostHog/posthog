import { BindLogic, BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { NotebookLogicProps, notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { AnyPropertyFilter, CustomerProfileScope, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

import { CustomerProfileMenu } from 'products/customer_analytics/frontend/components/CustomerProfileMenu'
import { FeedbackBanner } from 'products/customer_analytics/frontend/components/FeedbackBanner'
import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

type PersonProfileCanvasProps = {
    person: PersonType
    attachTo: BuiltLogic | LogicWrapper
}

const PersonProfileCanvas = ({ person, attachTo }: PersonProfileCanvasProps): JSX.Element | null => {
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
    const notebookLogicProps: NotebookLogicProps = {
        shortId,
        mode,
        canvasFiltersOverride: personFilter,
    }
    const mountedNotebookLogic = notebookLogic(notebookLogicProps)
    useAttachedLogic(mountedNotebookLogic, attachTo)

    return (
        <BindLogic logic={notebookLogic} props={notebookLogicProps}>
            <BindLogic logic={customerProfileLogic} props={customerProfileLogicProps}>
                <FeedbackBanner
                    feedbackButtonId="person-profile"
                    message="We're improving the persons experience. Send us your feedback!"
                />
                <CustomerProfileMenu />
                <Notebook
                    editable={false}
                    shortId={shortId}
                    mode={mode}
                    className="NotebookProfileCanvas"
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
