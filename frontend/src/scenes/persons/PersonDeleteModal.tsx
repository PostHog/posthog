import { useActions, useValues } from 'kea'
import { asDisplay } from './PersonHeader'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { PersonType } from '~/types'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'

export function PersonDeleteModal(): JSX.Element | null {
    const { personDeleteModal } = useValues(personDeleteModalLogic)
    const { deletePerson, showPersonDeleteModal } = useActions(personDeleteModalLogic)

    return (
        <LemonModal
            isOpen={!!personDeleteModal}
            onClose={() => showPersonDeleteModal(null)}
            title={`Are you sure you want to delete "${asDisplay(personDeleteModal)}"?`}
            description={
                <>
                    This action cannot be undone. If you opt to delete the person and its corresponding events, the
                    events will not be immediately removed. Instead these events will be deleted on a set schedule
                    during non-peak usage times.
                    <a
                        href="https://posthog.com/docs/privacy/data-deletion"
                        target="_blank"
                        rel="noopener"
                        className="font-bold"
                    >
                        {' '}
                        Learn more
                    </a>
                </>
            }
            footer={
                <>
                    <LemonButton
                        status="danger"
                        type="secondary"
                        onClick={() => {
                            deletePerson(personDeleteModal as PersonType, true)
                        }}
                        data-attr="delete-person-with-events"
                    >
                        Delete person and all corresponding events
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={() => showPersonDeleteModal(null)}
                        data-attr="delete-person-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={() => {
                            deletePerson(personDeleteModal as PersonType, false)
                        }}
                        data-attr="delete-person-no-events"
                    >
                        Delete person
                    </LemonButton>
                </>
            }
        />
    )
}
