import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { ExperimentEventExposureConfig } from '~/queries/schema/schema-general'
import type { Experiment, MultivariateFlagVariant } from '~/types'

const SIDE_PANEL_KEYS = {
    EXPERIMENT_TYPE: 'experiment-type',
    VARIANTS: 'experiment-variants',
    EXPOSURE_CRITERIA: 'experiment-exposure',
    METRICS: 'experiment-metrics',
} as const

type SidePanelKey = (typeof SIDE_PANEL_KEYS)[keyof typeof SIDE_PANEL_KEYS]

export type SidePanelProps = {
    experiment: Experiment
    onSelectPanel: (panelKey: SidePanelKey) => void
}

export const SidePanel = ({ experiment, onSelectPanel }: SidePanelProps): JSX.Element => {
    const isComplete = true
    const validationError = false
    return (
        <div className="space-y-4">
            <div className="bg-bg-light rounded p-4 border">
                <div className="flex items-center justify-between mb-4">
                    <h3 className="font-semibold">Experiment Summary</h3>
                </div>

                <LemonDivider className="mb-4" />

                <div className="space-y-6">
                    <div className="space-y-2">
                        <div className="flex items-center gap-2">
                            {isComplete ? (
                                <IconCheckCircle className="text-success w-5 h-5" />
                            ) : validationError ? (
                                <IconErrorOutline className="text-error w-5 h-5" />
                            ) : (
                                <div className="w-5 h-5 rounded-full border-2 border-border" />
                            )}
                            <div className="flex-1 font-semibold">Feature flag & variants</div>
                            <LemonButton
                                type={isComplete ? 'tertiary' : 'secondary'}
                                size="small"
                                onClick={() => onSelectPanel(SIDE_PANEL_KEYS.VARIANTS)}
                            >
                                Configure
                            </LemonButton>
                        </div>

                        <div className="flex gap-3 ml-7">
                            <div className="flex-1">
                                <div className="flex items-start justify-between gap-2">
                                    <div className="flex-1">
                                        {validationError && (
                                            <div className="text-sm text-error mb-2">
                                                you need a control and a test variant
                                            </div>
                                        )}
                                        <div className="text-sm text-muted">
                                            Set up your feature flag key and define test variants
                                        </div>

                                        <div className="text-sm space-y-1 mt-2">
                                            <div className="flex items-center gap-2 mb-2">
                                                <LemonTag type="primary" size="small">
                                                    Using default setup
                                                </LemonTag>
                                            </div>

                                            <div className="text-muted">
                                                Flag key:{' '}
                                                <span className="font-mono text-default">
                                                    {experiment.feature_flag_key}
                                                </span>
                                            </div>
                                            <div className="space-y-0.5">
                                                {experiment.parameters?.feature_flag_variants?.map(
                                                    (variant: MultivariateFlagVariant, index: number) => (
                                                        <div key={index} className="text-muted">
                                                            • {variant.key}: {variant.rollout_percentage}% of users
                                                        </div>
                                                    )
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center gap-2">
                            {isComplete ? (
                                <IconCheckCircle className="text-success w-5 h-5" />
                            ) : validationError ? (
                                <IconErrorOutline className="text-error w-5 h-5" />
                            ) : (
                                <div className="w-5 h-5 rounded-full border-2 border-border" />
                            )}
                            <div className="flex-1 font-semibold">
                                <span>Exposure criteria</span>
                                <LemonTag type="primary" size="small">
                                    Using default setup
                                </LemonTag>
                            </div>
                            <LemonButton
                                type={isComplete ? 'tertiary' : 'secondary'}
                                size="small"
                                onClick={() => onSelectPanel(SIDE_PANEL_KEYS.EXPOSURE_CRITERIA)}
                            >
                                Configure
                            </LemonButton>
                        </div>

                        <div className="flex gap-3 ml-7">
                            <div className="flex-1">
                                <div className="flex items-start justify-between gap-2">
                                    <div className="flex-1">
                                        {validationError && (
                                            <div className="text-sm text-error mb-2">
                                                you need a control and a test variant
                                            </div>
                                        )}
                                        <div className="text-sm text-muted">
                                            Set up your feature flag key and define test variants
                                        </div>

                                        <div className="text-sm space-y-1 mt-2">
                                            <div className="text-muted">
                                                {experiment.exposure_criteria?.filterTestAccounts !== false ? '✓' : '✗'}{' '}
                                                Filter test accounts
                                            </div>
                                            <div className="text-muted">
                                                • Exposure trigger:&nbsp;
                                                {experiment.exposure_criteria?.exposure_config
                                                    ? (
                                                          experiment.exposure_criteria
                                                              ?.exposure_config as ExperimentEventExposureConfig
                                                      ).event || 'Custom event'
                                                    : 'Feature flag exposure'}
                                            </div>
                                            <div className="text-muted">
                                                • Multi-variant:{' '}
                                                {experiment.exposure_criteria?.multiple_variant_handling ||
                                                    'Latest variant'}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center gap-2">
                            {isComplete ? (
                                <IconCheckCircle className="text-success w-5 h-5" />
                            ) : validationError ? (
                                <IconErrorOutline className="text-error w-5 h-5" />
                            ) : (
                                <div className="w-5 h-5 rounded-full border-2 border-border" />
                            )}
                            <div className="flex-1 font-semibold">Metrics</div>
                            <LemonButton
                                type={isComplete ? 'tertiary' : 'secondary'}
                                size="small"
                                onClick={() => onSelectPanel(SIDE_PANEL_KEYS.METRICS)}
                            >
                                Configure
                            </LemonButton>
                        </div>

                        <div className="flex gap-3 ml-7">
                            <div className="flex-1">
                                <div className="flex items-start justify-between gap-2">
                                    <div className="flex-1">
                                        {validationError && (
                                            <div className="text-sm text-error mb-2">
                                                you need a control and a test variant
                                            </div>
                                        )}
                                        <div className="text-sm text-muted">
                                            Set up your feature flag key and define test variants
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
