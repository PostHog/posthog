import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'

import { PersonType } from '~/types'

import { asDisplay } from './person-utils'

const DELETE_CONFIRMATION_TEXT = 'delete'

export function PersonDeleteModal(): JSX.Element | null {
    const { personDeleteModal, deleteConfirmationText } = useValues(personDeleteModalLogic)
    const [alsoDeleteEvents, setAlsoDeleteEvents] = useState(false)
    const [alsoDeleteRecordings, setAlsoDeleteRecordings] = useState(false)
    const { deletePerson, showPersonDeleteModal, setDeleteConfirmationText } = useActions(personDeleteModalLogic)

    const handleClose = (): void => {
        showPersonDeleteModal(null)
        setDeleteConfirmationText('')
        setAlsoDeleteEvents(false)
        setAlsoDeleteRecordings(false)
    }

    return (
        <LemonModal isOpen={!!personDeleteModal} onClose={handleClose} title="Confirm deletion" maxWidth="500px">
            <div className="space-y-4">
                <h4>Are you sure you want to delete "{asDisplay(personDeleteModal)}"?</h4>

                <p>This action cannot be undone.</p>
                <p>
                    If you opt to delete events and/or recordings, they will not be immediately removed. Instead they
                    are deleted on a set schedule during non-peak usage times.{' '}
                    <Link to="https://posthog.com/docs/privacy/data-deletion" target="_blank" className="font-bold">
                        Learn more
                    </Link>
                </p>
                <LemonCheckbox
                    onChange={setAlsoDeleteEvents}
                    checked={alsoDeleteEvents}
                    className="mt-3"
                    label="Also delete all corresponding events."
                />
                <LemonCheckbox
                    onChange={setAlsoDeleteRecordings}
                    checked={alsoDeleteRecordings}
                    className="mt-3"
                    label="Also delete all corresponding recordings."
                />

                <div className="space-y-2">
                    <label className="text-sm">
                        To confirm, please type <strong>{DELETE_CONFIRMATION_TEXT}</strong> below:
                    </label>
                    <LemonInput
                        value={deleteConfirmationText}
                        onChange={setDeleteConfirmationText}
                        placeholder={DELETE_CONFIRMATION_TEXT}
                        className="w-full"
                        autoFocus
                    />
                </div>
                <div className="bg-warning-highlight border border-warning rounded p-2 text-sm">
                    Do NOT delete this person if you want to re-use the distinct IDs. Instead use split ID. Re-using the
                    distinct ID of a deleted person is not supported and will result in a bad application state.
                </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
                <LemonButton type="secondary" onClick={handleClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    disabledReason={
                        deleteConfirmationText !== DELETE_CONFIRMATION_TEXT
                            ? 'Please type the correct confirmation text'
                            : undefined
                    }
                    onClick={() =>
                        deletePerson(personDeleteModal as PersonType, alsoDeleteEvents, alsoDeleteRecordings)
                    }
                >
                    Delete Person
                </LemonButton>
            </div>
        </LemonModal>
    )
}
