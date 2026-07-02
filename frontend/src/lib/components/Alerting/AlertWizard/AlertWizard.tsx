import { useActions, useValues } from 'kea'

import { AlertingWizardLayout } from 'lib/components/Alerting'
import type { AlertingWizardStep } from 'lib/components/Alerting'

import { WizardStep, alertWizardLogic } from './alertWizardLogic'
import { ConfigureStep } from './steps/ConfigureStep'
import { DestinationStep } from './steps/DestinationStep'
import { TriggerStep } from './steps/TriggerStep'

const ALL_STEPS: AlertingWizardStep<WizardStep>[] = [
    { key: WizardStep.Destination, label: 'Destination' },
    { key: WizardStep.Trigger, label: 'Trigger' },
    { key: WizardStep.Configure, label: 'Configure' },
]

export interface AlertWizardProps {
    onCancel: () => void
    onSwitchToTraditional: () => void
    hideTriggerStep?: boolean
    hideCloseButton?: boolean
}

export function AlertWizard({
    onCancel,
    onSwitchToTraditional,
    hideTriggerStep,
    hideCloseButton,
}: AlertWizardProps): JSX.Element {
    const { currentStep } = useValues(alertWizardLogic)
    const { setStep } = useActions(alertWizardLogic)
    const steps = hideTriggerStep ? ALL_STEPS.filter((step) => step.key !== WizardStep.Trigger) : ALL_STEPS

    return (
        <AlertingWizardLayout
            steps={steps}
            currentStep={currentStep}
            onStepClick={setStep}
            onCancel={onCancel}
            onSwitchToTraditional={onSwitchToTraditional}
            hideCloseButton={hideCloseButton}
        >
            {currentStep === WizardStep.Destination && <DestinationStep />}
            {currentStep === WizardStep.Trigger && !hideTriggerStep && <TriggerStep />}
            {currentStep === WizardStep.Configure && <ConfigureStep />}
        </AlertingWizardLayout>
    )
}
