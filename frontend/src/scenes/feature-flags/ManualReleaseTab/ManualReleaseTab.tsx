import { LemonButton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'

import { PersonType } from '~/types'
import { useState } from 'react'
import { Row } from 'antd'
import { manualReleaseLogic } from './manualReleaseLogic'
import { InstructionsModal } from './InstructionsModal'
import { EnrollmentSelectorModal } from './EnrollmentSelectorModal'
import { ManualReleaseList } from './ManualReleaseList'

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
        <div className="flex justify-center">
            <div className="mb-4 border rounded p-4 max-w-160">
                <div>
                    <b>Enable Manual Release for this Feature flag</b>
                </div>
                <div className="mb-3">
                    Manual Release conditions are the easiest way for you to have flexible control over who gets exposed
                    to your feature flags. With manual release conditions, you can:
                </div>

                <div className="mb-1 mt-2">
                    - Add and remove users from a feature flag without needing to specify property conditions
                </div>

                <div className="mb-2">
                    - Implement opt-in functionality for your users to self-determine if they would like to be exposed
                    to a feature flag
                </div>

                <Row justify="end">
                    <LemonButton
                        disabledReason={
                            featureFlag.filters.multivariate ? 'Beta only available for boolean flags' : null
                        }
                        type="primary"
                        onClick={enableManualCondition}
                    >
                        Enable
                    </LemonButton>
                </Row>
            </div>
        </div>
    )
}
