import { BindLogic, useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { AddPersonToCohortModalBody } from './AddPersonToCohortModalBody'
import { AddPersonToCohortModalProps, addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'

export function AddPersonToCohortModal({ id, tabId }: AddPersonToCohortModalProps): JSX.Element {
    const logicProps = { id, tabId }
    const logic = addPersonToCohortModalLogic(logicProps)
    const { hideAddPersonToCohortModal, addPersonsToCohort } = useActions(logic)
    const { addPersonToCohortModalVisible, personsToAddToCohort, isCohortUpdating } = useValues(logic)

    const hasUnsavedChanges = Object.keys(personsToAddToCohort).length > 0

    const handleClose = useCallback(() => {
        if (hasUnsavedChanges) {
            LemonDialog.open({
                title: 'Discard unsaved changes?',
                description: 'You have selected persons that haven\u2019t been saved to the cohort yet.',
                primaryButton: {
                    children: 'Discard',
                    status: 'danger',
                    onClick: hideAddPersonToCohortModal,
                },
                secondaryButton: {
                    children: 'Keep editing',
                },
            })
        } else {
            hideAddPersonToCohortModal()
        }
    }, [hasUnsavedChanges, hideAddPersonToCohortModal])

    return (
        <BindLogic logic={addPersonToCohortModalLogic} props={logicProps}>
            <LemonModal
                title="Add users to cohort"
                onClose={handleClose}
                closable={!isCohortUpdating}
                isOpen={addPersonToCohortModalVisible}
                footer={
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={handleClose}
                            disabled={isCohortUpdating}
                            data-attr="cohort-add-users-modal-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={async () => {
                                await addPersonsToCohort()
                            }}
                            loading={isCohortUpdating}
                            disabledReason={
                                Object.keys(personsToAddToCohort).length === 0 ? 'Select at least one user' : undefined
                            }
                            data-attr="cohort-add-users-modal-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <AddPersonToCohortModalBody />
            </LemonModal>
        </BindLogic>
    )
}
