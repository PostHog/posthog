import { LemonModal } from '@posthog/lemon-ui'

import { Survey } from '~/types'

import { NewSurvey } from '../constants'
import { SurveyBranchingFlow } from './SurveyBranchingFlow'

interface SurveyBranchingFlowModalProps {
    survey: Survey | NewSurvey
    isOpen: boolean
    onClose: () => void
}

export function SurveyBranchingFlowModal({ survey, isOpen, onClose }: SurveyBranchingFlowModalProps): JSX.Element {
    return (
        <LemonModal title="Survey flow" isOpen={isOpen} onClose={onClose} width="90vw">
            <div className="h-[70vh]">
                <SurveyBranchingFlow survey={survey} />
            </div>
        </LemonModal>
    )
}
