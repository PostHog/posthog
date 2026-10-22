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

    // Pinned to the bottom so the buttons stay put on every step. Equal-width button groups keep the link centered.
    const footer = (
        <div className="@container sticky bottom-0 z-10 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-primary bg-bg-light py-4">
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

    // Sized off the container, so the layout holds when the side panel narrows the scene. From 1024px the form is
    // centered with the guide on the right, and an empty left column as wide as the right keeps it centered. From
    // 672px the form and guide sit side by side, and narrower screens get one column with the guide under the form.
    const mainColumn =
        'w-full max-w-3xl min-w-0 justify-self-center space-y-6 @2xl:col-start-1 @2xl:max-w-none @5xl:col-start-2'
    // The second row fills the scene's height, so the footer stays at the same height whether or not the step scrolls
    return (
        <div className="@container flex flex-1 flex-col bg-bg-light">
            <div className="grid flex-1 grid-cols-1 grid-rows-[auto_1fr_auto] gap-6 px-6 pt-6 pb-6 @2xl:pb-0 @2xl:grid-cols-[minmax(0,1fr)_14rem] @2xl:grid-rows-[auto_1fr] @5xl:grid-cols-[minmax(14rem,1fr)_minmax(0,48rem)_minmax(14rem,1fr)]">
                <div className={mainColumn}>
                    {header}
                    {stepper}
                </div>
                <div className={cn(mainColumn, 'flex flex-col')}>
                    {body}
                    {footer}
                </div>
                <aside className="w-full max-w-3xl min-w-0 justify-self-center @2xl:col-start-2 @2xl:row-start-2 @2xl:max-w-80 @2xl:justify-self-start @5xl:col-start-3">
                    <ExperimentWizardGuide />
                </aside>
            </div>
        </div>
    )
}
