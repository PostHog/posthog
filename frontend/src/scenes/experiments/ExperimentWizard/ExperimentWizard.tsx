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
import { ImplementationStep } from './steps/ImplementationStep'
import { VariantsStep } from './steps/VariantsStep'

export function ExperimentWizard(): JSX.Element {
    const { currentStep, isLastStep, isFirstStep, isExperimentSubmitting, stepValidationErrors, hasFormErrors } =
        useValues(experimentWizardLogic)
    const { nextStep, prevStep, setStep, saveExperiment, openSavedExperiment } = useActions(experimentWizardLogic)
    const isImplementationStep = currentStep === 'implementation'

    const header = (
        <div className="space-y-1">
            <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.experiments()}>
                Experiments
            </LemonButton>
            <h1 className="text-2xl font-semibold">New experiment</h1>
        </div>
    )

    const stepper = (
        // A container of its own, so the stepper hides step labels based on the width of the form column
        <div className="@container flex justify-center">
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
            {isImplementationStep && <ImplementationStep />}
        </div>
    )

    // Pinned to the bottom of the scene, so the buttons and the no-code link stay in the same place on every step,
    // however tall the step is. Back and the primary button take equal space, which keeps the link centered. The
    // footer is its own container, so when the column is too narrow for one line the link wraps under the buttons.
    const footer = (
        <div className="@container sticky bottom-0 z-10 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-primary bg-bg-light py-4">
            <div className="flex flex-1 basis-0">
                {!isFirstStep && !isImplementationStep && (
                    <LemonButton type="secondary" onClick={prevStep}>
                        Back
                    </LemonButton>
                )}
            </div>
            {!isImplementationStep && (
                <p className="order-last m-0 w-full text-center text-xs text-muted @2xl:order-none @2xl:w-auto">
                    Looking for no-code? They are created using the toolbar,{' '}
                    <Link
                        target="_blank"
                        targetBlankIcon
                        to="https://posthog.com/docs/experiments/no-code-web-experiments"
                    >
                        see no-code docs
                    </Link>
                </p>
            )}
            <div className="flex flex-1 basis-0 items-center justify-end gap-2">
                {isImplementationStep ? (
                    <LemonButton
                        type="primary"
                        onClick={openSavedExperiment}
                        data-attr="experiment-wizard-go-to-experiment"
                    >
                        Go to experiment
                    </LemonButton>
                ) : isLastStep ? (
                    <LemonButton
                        type="primary"
                        // Stay in the wizard, which then shows the implementation step
                        onClick={() => saveExperiment(false)}
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

    // Three layouts, sized off the container rather than the viewport so they hold when the side panel narrows the
    // scene:
    // - 1024px and wider (laptops and up): the form is centered, with the guide in the right-hand column level with
    //   the form card. The left column is empty and always as wide as the right, so the side space shrinks evenly and
    //   the form stays centered, narrowing only once both sides are at their minimum.
    // - 672px to 1024px (tablets): the form and guide sit side by side and fill the width together, so the content
    //   as a whole is centered.
    // - Below 672px (phones): one centered column, with the guide under the form, and bottom padding after it.
    const mainColumn =
        'w-full max-w-3xl min-w-0 justify-self-center space-y-6 @2xl:col-start-1 @2xl:max-w-none @5xl:col-start-2'
    // The main column's second row fills the scene's height, and the footer adds its own bottom padding, so the
    // footer sits at the same height whether or not the step scrolls.
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
