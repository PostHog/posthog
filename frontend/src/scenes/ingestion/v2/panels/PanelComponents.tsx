import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { ingestionLogicV2, INGESTION_STEPS } from '../ingestionLogic'
import './Panels.scss'
import { IconArrowLeft } from 'lib/components/icons'
import { IngestionInviteMembersButton } from '../IngestionInviteMembersButton'

export function PanelFooter(): JSX.Element {
    const { next } = useActions(ingestionLogicV2)

    return (
        <div className="panel-footer">
            <LemonDivider thick dashed className="my-6" />
            <div>
                <LemonButton
                    type="primary"
                    size="large"
                    fullWidth
                    center
                    className="mb-2"
                    onClick={() => next({ readyToVerify: true })}
                >
                    Continue
                </LemonButton>
                <IngestionInviteMembersButton />
            </div>
        </div>
    )
}

export function PanelHeader(): JSX.Element | null {
    const { isSmallScreen, previousStep, currentStep } = useValues(ingestionLogicV2)
    const { onBack } = useActions(ingestionLogicV2)

    // no back buttons on the first screen
    if (currentStep === INGESTION_STEPS.START) {
        return null
    }

    return (
        <div className="flex items-center mb-2" data-attr="wizard-step-counter">
            <LemonButton type="tertiary" status="primary" onClick={onBack} icon={<IconArrowLeft />} size="small">
                {isSmallScreen ? '' : previousStep}
            </LemonButton>
        </div>
    )
}
