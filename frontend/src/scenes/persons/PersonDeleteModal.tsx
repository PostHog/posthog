import { LemonButton, LemonCheckbox, LemonModal, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'

import { PersonType } from '~/types'

import { asDisplay } from './person-utils'

export function PersonDeleteModal(): JSX.Element | null {
    const { personDeleteModal } = useValues(personDeleteModalLogic)
    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const { deletePerson, showPersonDeleteModal } = useActions(personDeleteModalLogic)

    return (
        <LemonModal
            isOpen={!!personDeleteModal}
            onClose={() => showPersonDeleteModal(null)}
            title={`Are you sure you want to delete "${asDisplay(personDeleteModal)}"?`}
            description={
                <>
                    <p>This action cannot be undone.</p>
                    <p>
                        If you want to re-use the distinct ids do NOT use delete person and instead use split IDs.
                        Re-using deleted person's distinct ids is not supported and will result in bad data state.
                    </p>
                    <p>
                        If you opt to delete the person and its corresponding events, the events will not be immediately
                        removed. Instead these events will be deleted on a set schedule during non-peak usage times.{' '}
                        <Link to="https://posthog.com/docs/privacy/data-deletion" target="_blank" className="font-bold">
                            Learn more
                        </Link>
                    </p>
                    <LemonCheckbox
                        onChange={(value) => setIsDeletionConfirmed(value)}
                        checked={isDeletionConfirmed}
                        className="mt-3"
                        label="I understand that re-using the same distinct_id will result in a bad state."
                    />
                </>
            }
            footer={
                <>
                    <LemonButton
                        status="danger"
                        type="tertiary"
                        onClick={() => deletePerson(personDeleteModal as PersonType, true)}
                        disabled={!isDeletionConfirmed}
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
                        type="secondary"
                        status="danger"
                        onClick={() => deletePerson(personDeleteModal as PersonType, false)}
                        disabled={!isDeletionConfirmed}
                        data-attr="delete-person-no-events"
                    >
                        Delete person
                    </LemonButton>
                </>
            }
        />
    )
}
