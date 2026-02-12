import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ExperimentWizardStepper } from './ExperimentWizardStepper'
import { experimentWizardLogic } from './experimentWizardLogic'
import { AboutStep } from './steps/AboutStep'
import { AnalyticsStep } from './steps/AnalyticsStep'
import { VariantsStep } from './steps/VariantsStep'

export function ExperimentWizard(): JSX.Element {
    const { currentStep, isLastStep, isFirstStep, isExperimentSubmitting } = useValues(experimentWizardLogic)
    const { nextStep, prevStep, setStep, saveExperiment, openFullEditor } = useActions(experimentWizardLogic)

    return (
        <div className="min-h-screen bg-bg-light">
            <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">
                {/* Header */}
                <div className="space-y-4">
                    <div className="space-y-1">
                        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.experiments()}>
                            Experiments
                        </LemonButton>
                        <h1 className="text-2xl font-semibold">New experiment</h1>
                    </div>
                    <div className="flex justify-center">
                        <ExperimentWizardStepper currentStep={currentStep} onStepClick={setStep} />
                    </div>
                </div>

                {/* Step content */}
                <div className="bg-surface-primary border border-border rounded-lg p-6">
                    {currentStep === 'about' && <AboutStep />}
                    {currentStep === 'variants' && <VariantsStep />}
                    {currentStep === 'analytics' && <AnalyticsStep />}
                </div>

                {/* Navigation */}
                <div className="flex items-center justify-between pt-4 border-t border-border">
                    <div>
                        {!isFirstStep && (
                            <LemonButton type="secondary" onClick={prevStep}>
                                Back
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        {!isLastStep && (
                            <LemonButton type="secondary" onClick={saveExperiment} loading={isExperimentSubmitting}>
                                Save as draft
                            </LemonButton>
                        )}
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
                        <button
                            type="button"
                            onClick={openFullEditor}
                            className="text-link hover:underline cursor-pointer"
                        >
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
                            read more
                        </Link>
                    </p>
                </div>
            </div>
        </div>
    )
}
