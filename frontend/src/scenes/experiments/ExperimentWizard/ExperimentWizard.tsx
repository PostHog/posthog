import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconLightBulb } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { ExperimentWizardGuide } from './ExperimentWizardGuide'
import { ExperimentWizardStepper } from './ExperimentWizardStepper'
import { experimentWizardLogic } from './experimentWizardLogic'
import { AboutStep } from './steps/AboutStep'
import { AnalyticsStep } from './steps/AnalyticsStep'
import { VariantsStep } from './steps/VariantsStep'

export function ExperimentWizard(): JSX.Element {
    const { currentStep, isLastStep, isFirstStep, isExperimentSubmitting, showGuide, stepValidationErrors } =
        useValues(experimentWizardLogic)
    const { nextStep, prevStep, setStep, saveExperiment, openFullEditor, toggleGuide } =
        useActions(experimentWizardLogic)

    const header = (
        <div className="flex items-center justify-between">
            <div className="space-y-1">
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.experiments()}>
                    Experiments
                </LemonButton>
                <h1 className="text-2xl font-semibold">New experiment</h1>
            </div>
            {!showGuide && (
                <LemonButton type="secondary" size="small" icon={<IconLightBulb />} onClick={toggleGuide}>
                    Show guide
                </LemonButton>
            )}
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
                        <LemonButton type="primary" onClick={saveExperiment} loading={isExperimentSubmitting}>
                            Save as draft
                        </LemonButton>
                    ) : (
                        <LemonButton type="primary" onClick={nextStep}>
                            Continue
                        </LemonButton>
                    )}
                </div>
            </div>

            <div className="text-center text-xs text-muted space-y-1">
                <p>
                    Prefer the old layout?{' '}
                    <button type="button" onClick={openFullEditor} className="text-link hover:underline cursor-pointer">
                        Open full editor
                    </button>
                </p>
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

    return (
        <div className="min-h-screen bg-bg-light">
            <div className={cn('mx-auto px-6 py-6 space-y-6', showGuide ? 'max-w-5xl' : 'max-w-3xl')}>
                {header}

                {showGuide ? (
                    <div className="grid grid-cols-[1fr_280px] gap-6">
                        <div className="space-y-6">
                            {stepper}
                            {body}
                            {footer}
                        </div>
                        <ExperimentWizardGuide />
                    </div>
                ) : (
                    <div className="space-y-6">
                        {stepper}
                        {body}
                        {footer}
                    </div>
                )}
            </div>
        </div>
    )
}
