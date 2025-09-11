import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AddPersonToCohortModalBody } from './AddPersonToCohortModalBody'
import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { CohortLogicProps } from './cohortEditLogic'

export function AddPersonToCohortModal({ id }: CohortLogicProps): JSX.Element {
    const logicProps = { id }
    const logic = addPersonToCohortModalLogic(logicProps)
    const { hideAddPersonToCohortModal, addPersonsToCohort } = useActions(logic)
    const { addPersonToCohortModalVisible, personsToAddToCohort, isCohortUpdating } = useValues(logic)
    return (
        <BindLogic logic={addPersonToCohortModalLogic} props={{ id }}>
            <LemonModal
                title="Add users to cohort"
                onClose={hideAddPersonToCohortModal}
                isOpen={addPersonToCohortModalVisible}
                footer={
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => hideAddPersonToCohortModal()}>
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
