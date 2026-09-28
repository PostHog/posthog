import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ExperimentWizardGuide } from './ExperimentWizardGuide'
import { experimentWizardLogic } from './experimentWizardLogic'
import { ExperimentWizardStepper } from './ExperimentWizardStepper'
import { AboutStep } from './steps/AboutStep'
import { AnalyticsStep } from './steps/AnalyticsStep'
import { VariantsStep } from './steps/VariantsStep'

export function ExperimentWizard(): JSX.Element {
    const { currentStep, isLastStep, isFirstStep, isExperimentSubmitting, stepValidationErrors, hasFormErrors } =
        useValues(experimentWizardLogic)
    const { nextStep, prevStep, setStep, saveExperiment } = useActions(experimentWizardLogic)

    const header = (
        <div className="space-y-1">
            <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.experiments()}>
                Experiments
            </LemonButton>
            <h1 className="text-2xl font-semibold">New experiment</h1>
        </div>
    )

    const stepper = (
        <div className="flex justify-center">
            <ExperimentWizardStepper
                currentStep={currentStep}
                onStepClick={setStep}
                stepErrors={stepValidationErrors}
            />
        </div>
    )

    const body = (
        <div className="bg-surface-primary border border-border rounded-lg p-6">
            {currentStep === 'about' && <AboutStep />}
            {currentStep === 'variants' && <VariantsStep />}
            {currentStep === 'analytics' && <AnalyticsStep />}
        </div>
    )

    const footer = (
        <>
            <div className="flex items-center justify-between">
                <div>
                    {!isFirstStep && (
                        <LemonButton type="secondary" onClick={prevStep}>
                            Back
                        </LemonButton>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    {isLastStep ? (
                        <LemonButton
                            type="primary"
                            onClick={saveExperiment}
                            loading={isExperimentSubmitting}
                            disabledReason={hasFormErrors ? 'Please fix all errors before saving' : undefined}
                        >
                            Save as draft
                        </LemonButton>
                    ) : (
                        <LemonButton type="primary" onClick={nextStep}>
                            Continue
                        </LemonButton>
                    )}
                </div>
            </div>

            <div className="text-center text-xs text-muted">
                <p>
                    Looking for no-code? They are created using the toolbar,{' '}
                    <Link
                        target="_blank"
                        targetBlankIcon
                        to="https://posthog.com/docs/experiments/no-code-web-experiments"
                    >
                        see no-code docs
                    </Link>
                </p>
            </div>
        </>
    )

    // The main column stays centered in the page, with the guide in a right-hand column that starts level with
    // the form card. Sized off the container rather than the viewport, so the layout holds when the side panel
    // narrows the scene. Below that width the guide stacks under the main column.
    const mainColumn = 'w-full max-w-3xl min-w-0 justify-self-center space-y-6 @5xl:col-start-2 @5xl:max-w-none'
    return (
        <div className="@container flex-1 bg-bg-light">
            <div className="grid grid-cols-1 gap-6 px-6 py-6 @5xl:grid-cols-[minmax(0,1fr)_minmax(0,48rem)_minmax(16rem,1fr)]">
                <div className={mainColumn}>
                    {header}
                    {stepper}
                </div>
                <div className={mainColumn}>
                    {body}
                    {footer}
                </div>
                <aside className="w-full max-w-3xl min-w-0 justify-self-center @5xl:col-start-3 @5xl:row-start-2 @5xl:max-w-80 @5xl:justify-self-start">
                    <ExperimentWizardGuide />
                </aside>
            </div>
        </div>
    )
}
