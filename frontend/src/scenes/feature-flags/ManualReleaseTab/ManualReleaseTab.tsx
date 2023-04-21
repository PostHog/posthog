import { BindLogic, useActions, useValues } from 'kea'

import { PersonType } from '~/types'
import { useState } from 'react'
import { manualReleaseLogic } from './manualReleaseLogic'
import { InstructionsModal } from './InstructionsModal'
import { EnrollmentSelectorModal } from './EnrollmentSelectorModal'
import { ManualReleaseList } from './ManualReleaseList'
import { EnableManualReleasePrompt } from './EnableManualReleasePrompt'

interface FeatureProps {
    id: number
}

export function ManualReleaseTab({ id }: FeatureProps): JSX.Element {
    const [selectedPersons, setSelectedPersons] = useState<PersonType[]>([])

    const logic = manualReleaseLogic({ id })
    const { implementOptInInstructionsModal, enrollmentModal, featureFlag, hasManualRelease } = useValues(logic)
    const { toggleImplementOptInInstructionsModal, toggleEnrollmentModal, enableManualCondition } = useActions(logic)

    return hasManualRelease ? (
        <BindLogic logic={manualReleaseLogic} props={{ id }}>
            <ManualReleaseList localPersons={selectedPersons} />
            <EnrollmentSelectorModal
                onAdded={(persons) => setSelectedPersons(persons)}
                featureFlag={featureFlag}
                visible={enrollmentModal}
                onClose={toggleEnrollmentModal}
            />
            <InstructionsModal
                featureFlag={featureFlag}
                visible={implementOptInInstructionsModal}
                onClose={toggleImplementOptInInstructionsModal}
            />
        </BindLogic>
    ) : (
        <EnableManualReleasePrompt featureFlag={featureFlag} onEnable={enableManualCondition} />
    )
}
