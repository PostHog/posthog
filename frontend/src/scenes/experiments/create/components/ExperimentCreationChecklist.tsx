import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { createExperimentLogic } from '../createExperimentLogic'

interface ChecklistStep {
    key: string
    title: string
    description: string
    isComplete: boolean
    action?: () => void
    actionLabel?: string
    isOptional?: boolean
    comingSoon?: boolean
}

interface ExperimentCreationChecklistProps {
    onPanelSelect: (panelKey: string) => void
}

export function ExperimentCreationChecklist({ onPanelSelect }: ExperimentCreationChecklistProps): JSX.Element {
    const { experiment, hasTargeting, hasPrimaryMetrics } = useValues(createExperimentLogic)

    // Check completion status for each step
    const hasValidFeatureFlag = !!(
        experiment.feature_flag_key && experiment.parameters?.feature_flag_variants?.length >= 2
    )

    const hasExposureCriteria = !!(
        experiment.exposure_criteria?.filterTestAccounts !== undefined ||
        experiment.exposure_criteria?.exposure_config ||
        experiment.exposure_criteria?.multiple_variant_handling
    )

    const steps: ChecklistStep[] = [
        {
            key: 'feature-flag',
            title: 'Feature Flag & Variants',
            description: 'Set up your feature flag key and define test variants',
            isComplete: hasValidFeatureFlag,
            action: () => onPanelSelect('experiment-variants'),
            actionLabel: 'Configure variants',
        },
        {
            key: 'exposure-criteria',
            title: 'Exposure Criteria',
            description: 'Configure when users are considered exposed to the experiment',
            isComplete: hasExposureCriteria,
            action: () => onPanelSelect('experiment-exposure'),
            actionLabel: 'Set criteria',
        },
        {
            key: 'metrics',
            title: 'Metrics',
            description: "Define your experiment's success metrics",
            isComplete: hasPrimaryMetrics,
            action: () => onPanelSelect('experiment-metrics'),
            actionLabel: 'Add metrics',
        },
        {
            key: 'targeting',
            title: 'Targeting',
            description: 'Define your target audience (optional)',
            isComplete: hasTargeting,
            action: () => onPanelSelect('experiment-targeting'),
            actionLabel: 'Set targeting',
            isOptional: true,
        },
    ]

    const completedSteps = steps.filter((step) => step.isComplete).length
    const totalRequiredSteps = steps.filter((step) => !step.isOptional).length

    return (
        <div className="space-y-4">
            <div className="bg-bg-light rounded p-4 border space-y-4">
                {steps.map((step) => (
                    <div key={step.key} className="flex gap-3">
                        {step.isComplete ? (
                            <IconCheckCircle className="text-success flex-none w-6 h-6" />
                        ) : (
                            <div className="flex-none w-5 h-5 rounded-full border-2 border-orange mt-0.5" />
                        )}

                        <div className="flex-1 space-y-1">
                            <div>
                                <div className={`font-semibold ${step.isComplete ? 'text-muted line-through' : ''}`}>
                                    {step.title}
                                </div>
                                <div
                                    className={`text-sm ${step.isComplete ? 'text-muted line-through' : 'text-muted'}`}
                                >
                                    {step.description}
                                </div>
                            </div>

                            {!step.isComplete && step.action && !step.comingSoon && (
                                <div className="pt-1">
                                    <LemonButton type="secondary" size="small" onClick={step.action}>
                                        {step.actionLabel}
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            {completedSteps >= totalRequiredSteps && (
                <div className="bg-success-highlight border border-success rounded p-3">
                    <div className="flex items-center gap-2">
                        <IconCheckCircle className="text-success flex-none w-5 h-5" />
                        <div className="text-sm font-medium text-success">
                            Ready to save! All required steps completed.
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
