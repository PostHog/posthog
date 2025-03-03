import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'

export function PreLaunchChecklist(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { openDescriptionModal, openPrimaryMetricSourceModal, openCalculateRunningTimeModal } =
        useActions(experimentLogic)
    return (
        <div className="w-1/2 mt-8 xl:mt-0">
            <div className="bg-bg-light rounded p-4 border">
                <div className="mb-4">
                    <div className="font-semibold text-lg">Pre-launch checklist</div>
                </div>
                <div>
                    {/* Step 1 - Hypothesis */}
                    <div className="flex gap-3 mb-6">
                        {experiment.description ? (
                            <IconCheckCircle className="text-success flex-none w-6 h-6" />
                        ) : (
                            <div className="flex-none w-5 h-5 rounded-full border-2 border-orange" />
                        )}
                        <div className="flex-1">
                            <div className={`text-xs font-semibold ${experiment.description ? 'text-success' : ''}`}>
                                Step 1
                            </div>
                            <div className="flex items-center justify-between">
                                <div>
                                    <div
                                        className={`font-semibold ${
                                            experiment.description ? 'text-muted line-through' : ''
                                        }`}
                                    >
                                        Add hypothesis
                                    </div>
                                    <div
                                        className={`text-sm ${
                                            experiment.description ? 'text-muted line-through' : 'text-muted'
                                        }`}
                                    >
                                        Document what you expect to learn from this experiment
                                    </div>
                                </div>
                                {!experiment.description && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => {
                                            openDescriptionModal()
                                        }}
                                    >
                                        Add hypothesis
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Step 2 - Metric */}
                    <div className="flex gap-3 mb-6">
                        {experiment.metrics?.length > 0 ? (
                            <IconCheckCircle className="text-success flex-none w-6 h-6" />
                        ) : (
                            <div className="flex-none w-5 h-5 rounded-full border-2 border-orange" />
                        )}
                        <div className="flex-1">
                            <div
                                className={`text-xs font-semibold ${
                                    experiment.metrics?.length > 0 ? 'text-success' : ''
                                }`}
                            >
                                Step 2
                            </div>
                            <div className="flex items-center justify-between">
                                <div>
                                    <div
                                        className={`font-semibold ${
                                            experiment.metrics?.length > 0 ? 'text-muted line-through' : ''
                                        }`}
                                    >
                                        Add first metric
                                    </div>
                                    <div
                                        className={`text-sm ${
                                            experiment.metrics?.length > 0 ? 'text-muted line-through' : 'text-muted'
                                        }`}
                                    >
                                        Define your experiment's primary success metric
                                    </div>
                                </div>
                                {!(experiment.metrics?.length > 0) && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => {
                                            openPrimaryMetricSourceModal()
                                        }}
                                    >
                                        Add metric
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Step 3 - Running time */}
                    <div className="flex gap-3">
                        {experiment.parameters?.recommended_running_time ? (
                            <IconCheckCircle className="text-success flex-none w-6 h-6" />
                        ) : (
                            <div className="flex-none w-5 h-5 rounded-full border-2 border-orange" />
                        )}
                        <div className="flex-1">
                            <div
                                className={`text-xs font-semibold ${
                                    experiment.parameters?.recommended_running_time ? 'text-success' : ''
                                }`}
                            >
                                Step 3
                            </div>
                            <div className="flex items-center justify-between">
                                <div>
                                    <div
                                        className={`font-semibold ${
                                            experiment.parameters?.recommended_running_time
                                                ? 'text-muted line-through'
                                                : ''
                                        }`}
                                    >
                                        Calculate experiment duration
                                    </div>
                                    <div
                                        className={`text-sm ${
                                            experiment.parameters?.recommended_running_time
                                                ? 'text-muted line-through'
                                                : 'text-muted'
                                        }`}
                                    >
                                        Determine how long your experiment needs to run
                                    </div>
                                </div>
                                {!experiment.parameters?.recommended_running_time && experiment.metrics?.length > 0 && (
                                    <LemonButton type="secondary" size="small" onClick={openCalculateRunningTimeModal}>
                                        Calculate
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
