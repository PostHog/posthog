import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCheckbox } from '@posthog/lemon-ui'

import { getReplayVisionEditDisabledReason } from 'products/replay_vision/frontend/utils/accessControl'

import { ExposureCriteriaPanel } from '../../ExperimentForm/ExposureCriteriaPanel'
import { MetricsPanel } from '../../ExperimentForm/MetricsPanel'
import { experimentWizardLogic } from '../experimentWizardLogic'

export function AnalyticsStep(): JSX.Element {
    const { createReplayVisionScanner, experiment, sharedMetrics } = useValues(experimentWizardLogic)
    const { setCreateReplayVisionScanner, setExperiment, setExposureCriteria, setSharedMetrics } =
        useActions(experimentWizardLogic)

    return (
        <div className="space-y-6">
            <div className="space-y-4">
                <div>
                    <h3 className="text-lg font-semibold mb-1">Who is included in the analysis?</h3>
                    <ExposureCriteriaPanel experiment={experiment} onChange={setExposureCriteria} compact />
                </div>

                <div className="mt-10">
                    <h3 className="text-lg font-semibold mb-1">How to measure impact?</h3>
                    <MetricsPanel
                        experiment={experiment}
                        sharedMetrics={sharedMetrics}
                        compact
                        onSaveMetric={(metric, context) => {
                            const isNew = !experiment[context.field].some((m) => m.uuid === metric.uuid)
                            setExperiment({
                                ...experiment,
                                [context.field]: isNew
                                    ? [...experiment[context.field], metric]
                                    : experiment[context.field].map((m) => (m.uuid === metric.uuid ? metric : m)),
                            })
                        }}
                        onDeleteMetric={(metric, context) => {
                            if (metric.isSharedMetric) {
                                setExperiment({
                                    ...experiment,
                                    saved_metrics: (experiment.saved_metrics ?? []).filter(
                                        (sm) => sm.saved_metric !== metric.sharedMetricId
                                    ),
                                })
                                setSharedMetrics({
                                    ...sharedMetrics,
                                    [context.type]: sharedMetrics[context.type].filter((m) => m.uuid !== metric.uuid),
                                })
                                return
                            }
                            setExperiment({
                                ...experiment,
                                [context.field]: experiment[context.field].filter(({ uuid }) => uuid !== metric.uuid),
                            })
                        }}
                        onSaveSharedMetrics={(metrics, context) => {
                            setExperiment({
                                ...experiment,
                                saved_metrics: [
                                    ...(experiment.saved_metrics ?? []),
                                    ...metrics.map((metric) => ({
                                        saved_metric: metric.sharedMetricId,
                                    })),
                                ],
                            })
                            setSharedMetrics({
                                ...sharedMetrics,
                                [context.type]: [...sharedMetrics[context.type], ...metrics],
                            })
                        }}
                        onSaveExposureCriteria={setExposureCriteria}
                    />
                </div>
            </div>

            <LemonCheckbox
                bordered
                fullWidth
                checked={createReplayVisionScanner}
                onChange={setCreateReplayVisionScanner}
                disabledReason={getReplayVisionEditDisabledReason() ?? undefined}
                data-attr="experiment-create-replay-vision-scanner"
                label={
                    <div className="py-3">
                        <div className="font-semibold">Watch participant behavior with Replay Vision</div>
                        <div className="mt-1 font-normal text-sm text-muted">
                            Set up a scanner that classifies what participants do after experiment exposure. It is
                            created turned off, so nothing is scanned and no credits are used until you turn it on. You
                            can adjust its prompt, filters, and sampling first. A scanner keeps running after the
                            experiment ends, so turn it off when you are done.
                        </div>
                    </div>
                }
            />

            <LemonBanner type="info">
                You can always refine your analytics configuration and metrics after saving.
            </LemonBanner>
        </div>
    )
}
