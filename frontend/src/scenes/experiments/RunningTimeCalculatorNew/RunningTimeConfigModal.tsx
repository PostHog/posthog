import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Label } from 'lib/ui/Label/Label'

import { Experiment } from '~/types'

import { ManualCalculatorMetricType } from './calculations'
import { runningTimeLogic } from './runningTimeLogic'

export interface RunningTimeConfigModalProps {
    experimentId: Experiment['id']
    tabId: string
}

const METRIC_TYPE_OPTIONS: { value: ManualCalculatorMetricType; label: string }[] = [
    { value: 'funnel', label: 'Funnel' },
    { value: 'mean_count', label: 'Count' },
    { value: 'mean_sum_or_avg', label: 'Sum/Avg' },
]

function getBaselineLabel(metricType: ManualCalculatorMetricType): string {
    switch (metricType) {
        case 'funnel':
            return 'Baseline conversion rate'
        case 'mean_count':
            return 'Avg events per user'
        case 'mean_sum_or_avg':
            return 'Avg property value per user'
    }
}

function getBaselineHelp(metricType: ManualCalculatorMetricType): string {
    switch (metricType) {
        case 'funnel':
            return 'Expected conversion rate for the control group (0-100%)'
        case 'mean_count':
            return 'Average number of events per user in the control group'
        case 'mean_sum_or_avg':
            return 'Average property value per user in the control group'
    }
}

export function RunningTimeConfigModal({ experimentId, tabId }: RunningTimeConfigModalProps): JSX.Element {
    const {
        config,
        manualFormPreview,
        currentExposures,
        targetSampleSize,
        dailyExposureRate,
        remainingDays,
        isRunningTimeConfigModalOpen,
    } = useValues(runningTimeLogic({ experimentId, tabId }))
    const { setConfig, save, cancel } = useActions(runningTimeLogic({ experimentId, tabId }))

    const hasAutomaticData = remainingDays !== null

    return (
        <LemonModal
            isOpen={isRunningTimeConfigModalOpen}
            onClose={cancel}
            title="Running time configuration"
            width={480}
            footer={
                <div className="flex items-center gap-2 justify-end">
                    <LemonButton type="secondary" onClick={cancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={save}>
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-6">
                <div>
                    <Label intent="menu">Calculation mode</Label>
                    <LemonSegmentedButton
                        className="mt-1"
                        size="small"
                        fullWidth
                        options={[
                            { value: 'automatic', label: 'Automatic' },
                            { value: 'manual', label: 'Manual' },
                        ]}
                        value={config.mode}
                        onChange={(value) => setConfig({ mode: value as 'automatic' | 'manual' })}
                    />
                    <div className="text-xs text-muted mt-1">
                        {config.mode === 'manual'
                            ? 'Enter your own values to calculate sample size and running time.'
                            : 'Uses actual experiment data to calculate estimates.'}
                    </div>
                </div>

                {config.mode === 'manual' ? (
                    <>
                        <div>
                            <Label intent="menu">Metric type</Label>
                            <LemonSegmentedButton
                                className="mt-1"
                                size="small"
                                fullWidth
                                options={METRIC_TYPE_OPTIONS}
                                value={config.metricType}
                                onChange={(value) => setConfig({ metricType: value as ManualCalculatorMetricType })}
                            />
                        </div>

                        <div>
                            <Label intent="menu">{getBaselineLabel(config.metricType)}</Label>
                            <div className="flex items-center gap-1 mt-1">
                                <LemonInput
                                    type="number"
                                    value={config.baselineValue}
                                    onChange={(value) => setConfig({ baselineValue: value as number })}
                                    min={0}
                                    max={config.metricType === 'funnel' ? 100 : undefined}
                                    step={config.metricType === 'funnel' ? 0.1 : 1}
                                    className="flex-1"
                                />
                                {config.metricType === 'funnel' && <span className="text-muted">%</span>}
                            </div>
                            <div className="text-xs text-muted mt-1">{getBaselineHelp(config.metricType)}</div>
                        </div>

                        <div>
                            <Label intent="menu">Minimum detectable effect</Label>
                            <div className="flex items-center gap-3">
                                <div className="flex-[3]">
                                    <LemonSlider
                                        value={config.mde}
                                        onChange={(value) => setConfig({ mde: Math.round(value * 10) / 10 })}
                                        min={1}
                                        max={100}
                                        step={0.1}
                                    />
                                </div>
                                <div className="flex-1 flex items-center gap-1">
                                    <LemonInput
                                        type="number"
                                        value={config.mde}
                                        onChange={(value) => setConfig({ mde: Number(value) || 1 })}
                                        min={1}
                                        max={100}
                                        step={0.1}
                                        className="flex-1"
                                    />
                                    <span className="text-muted">%</span>
                                </div>
                            </div>
                            <div className="text-xs text-muted mt-1">
                                The smallest delta (change) you want to be able to measure with statistical
                                significance. Changing this setting does not impact the statistical analysis, only the
                                estimated runtime. Lower values require more data and longer run times.
                            </div>
                        </div>

                        <div>
                            <Label intent="menu">Expected exposures per day</Label>
                            <LemonInput
                                type="number"
                                value={config.exposureRate}
                                onChange={(value) => setConfig({ exposureRate: value as number })}
                                min={0}
                                step={100}
                                className="w-32 mt-1"
                            />
                            <div className="text-xs text-muted mt-1">
                                Total users entering the experiment per day (across all variants).
                            </div>
                        </div>

                        <div className="border-t pt-4 mt-4">
                            <Label intent="menu">Calculated results</Label>
                            <div className="grid grid-cols-2 gap-4 mt-2">
                                <div>
                                    <div className="text-xs text-muted">Recommended sample size</div>
                                    <div className="font-semibold">
                                        {manualFormPreview.sampleSize
                                            ? manualFormPreview.sampleSize.toLocaleString()
                                            : '—'}
                                    </div>
                                </div>
                                <div>
                                    <div className="text-xs text-muted">Estimated running time</div>
                                    <div className="font-semibold">
                                        {manualFormPreview.runningTime
                                            ? `~${manualFormPreview.runningTime} day${manualFormPreview.runningTime !== 1 ? 's' : ''}`
                                            : '—'}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </>
                ) : (
                    <>
                        {!hasAutomaticData ? (
                            <LemonBanner type="info">
                                Waiting for sufficient data to calculate time estimates. Need at least 1 day and 100
                                exposures.
                            </LemonBanner>
                        ) : (
                            <>
                                <div>
                                    <Label intent="menu">Remaining time</Label>
                                    <div className="metric-cell">
                                        {remainingDays === 0 ? (
                                            <span className="inline-flex items-center gap-1">
                                                <IconCheck className="text-success" />
                                                Complete
                                            </span>
                                        ) : (
                                            `~${Math.ceil(remainingDays)} day${Math.ceil(remainingDays) !== 1 ? 's' : ''}`
                                        )}
                                    </div>
                                </div>
                                <div>
                                    <Label intent="menu">Progress</Label>
                                    <div className="metric-cell">
                                        {currentExposures !== null && targetSampleSize !== null
                                            ? `${currentExposures.toLocaleString()} / ${targetSampleSize.toLocaleString()} exposures`
                                            : '—'}
                                    </div>
                                </div>
                                <div>
                                    <Label intent="menu">Rate</Label>
                                    <div className="metric-cell">
                                        {dailyExposureRate !== null
                                            ? `~${Math.round(dailyExposureRate).toLocaleString()} exposures/day`
                                            : '—'}
                                    </div>
                                </div>
                            </>
                        )}
                        <div>
                            <Label intent="menu">Minimum detectable effect</Label>
                            <div className="flex items-center gap-3">
                                <div className="flex-[3]">
                                    <LemonSlider
                                        value={config.mde}
                                        onChange={(value) => setConfig({ mde: Math.round(value * 10) / 10 })}
                                        min={1}
                                        max={100}
                                        step={0.1}
                                    />
                                </div>
                                <div className="flex-1 flex items-center gap-1">
                                    <LemonInput
                                        type="number"
                                        value={config.mde}
                                        onChange={(value) => setConfig({ mde: Number(value) || 1 })}
                                        min={1}
                                        max={100}
                                        step={0.1}
                                        className="flex-1"
                                    />
                                    <span className="text-muted">%</span>
                                </div>
                            </div>
                            <div className="text-xs text-muted mt-1">
                                The smallest delta (change) you want to be able to measure with statistical
                                significance. Changing this setting does not impact the statistical analysis, only the
                                estimated runtime. Lower values require more data and longer run times.
                            </div>
                        </div>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
