import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
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
        // Grows to meet the footer, so short steps don't change the card's height
        <div className="flex-1 bg-surface-primary border border-border rounded-lg p-6">
            {currentStep === 'about' && <AboutStep />}
            {currentStep === 'variants' && <VariantsStep />}
            {currentStep === 'analytics' && <AnalyticsStep />}
        </div>
    )

    // Pinned to the bottom of the scene, so the buttons and the no-code link stay in the same place on every step,
    // however tall the step is. Back and the primary button take equal space, which keeps the link centered.
    const footer = (
        <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-primary bg-bg-light py-4">
            <div className="flex flex-1 basis-0">
                {!isFirstStep && (
                    <LemonButton type="secondary" onClick={prevStep}>
                        Back
                    </LemonButton>
                )}
            </div>
            <p className="order-last m-0 w-full text-center text-xs text-muted @2xl:order-none @2xl:w-auto">
                Looking for no-code? They are created using the toolbar,{' '}
                <Link target="_blank" targetBlankIcon to="https://posthog.com/docs/experiments/no-code-web-experiments">
                    see no-code docs
                </Link>
            </p>
            <div className="flex flex-1 basis-0 items-center justify-end gap-2">
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
    )

    // The main column stays centered in the page, with the guide in a right-hand column that starts level with
    // the form card. Sized off the container rather than the viewport, so the layout holds when the side panel
    // narrows the scene. Below that width the guide stacks under the main column.
    const mainColumn = 'w-full max-w-3xl min-w-0 justify-self-center space-y-6 @5xl:col-start-2 @5xl:max-w-none'
    // The main column's second row fills the scene's height, and the footer adds its own bottom padding, so the
    // footer sits at the same height whether or not the step scrolls.
    return (
        <div className="@container flex flex-1 flex-col bg-bg-light">
            <div className="grid flex-1 grid-cols-1 grid-rows-[auto_1fr_auto] gap-6 px-6 pt-6 @5xl:grid-cols-[minmax(0,1fr)_minmax(0,48rem)_minmax(16rem,1fr)] @5xl:grid-rows-[auto_1fr]">
                <div className={mainColumn}>
                    {header}
                    {stepper}
                </div>
                <div className={cn(mainColumn, 'flex flex-col')}>
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
