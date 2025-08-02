import { BindLogic, useActions, useValues } from 'kea'
import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { LemonModal } from '@posthog/lemon-ui'
import { AddPersonToChortModalBody } from './AddPersonToCohortModalBody'
import { CohortLogicProps } from './cohortEditLogic'

export function AddPersonToCohortModal({ id }: CohortLogicProps): JSX.Element {
    const logicProps = { id }
    const logic = addPersonToCohortModalLogic(logicProps)
    const { hideAddPersonToCohortModal } = useActions(logic)
    const { addPersonToCohortModalVisible } = useValues(logic)
    return (
        <BindLogic logic={addPersonToCohortModalLogic} props={{ id }}>
            <LemonModal
                title="Add person to cohort"
                onClose={hideAddPersonToCohortModal}
                isOpen={addPersonToCohortModalVisible}
            >
                <AddPersonToChortModalBody />
            </LemonModal>
        </BindLogic>
    )
}
