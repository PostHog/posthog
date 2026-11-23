import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { AlertWizardProps } from './AlertWizard'
import { WizardStep, alertWizardLogic } from './alertWizardLogic'
import { QuillAlertWizardStepper } from './QuillAlertWizardStepper'
import { QuillConfigureStep } from './steps/QuillConfigureStep'
import { QuillDestinationStep } from './steps/QuillDestinationStep'
import { QuillTriggerStep } from './steps/QuillTriggerStep'

export function QuillAlertWizard({
    onCancel,
    onSwitchToTraditional,
    hideTriggerStep,
    hideCloseButton,
}: AlertWizardProps): JSX.Element {
    const { currentStep } = useValues(alertWizardLogic)
    const { setStep } = useActions(alertWizardLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <QuillAlertWizardStepper
                    currentStep={currentStep}
                    onStepClick={setStep}
                    hideTriggerStep={hideTriggerStep}
                />
                {hideCloseButton ? null : (
                    <Button size="icon" onClick={onCancel} aria-label="Close wizard" tooltip="Close wizard">
                        <IconX />
                    </Button>
                )}
            </div>

            <div className="flex w-full max-w-lg flex-col">
                {currentStep === WizardStep.Destination && <QuillDestinationStep />}
                {currentStep === WizardStep.Trigger && !hideTriggerStep && <QuillTriggerStep />}
                {currentStep === WizardStep.Configure && <QuillConfigureStep />}
            </div>

            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Need more control?{' '}
                <Button variant="link" size="inline" onClick={onSwitchToTraditional}>
                    Go back to traditional editor
                </Button>
            </Text>
        </div>
    )
}
