import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { ExposureCriteriaPanel } from '../../ExperimentForm/ExposureCriteriaPanel'
import { MetricsPanel } from '../../ExperimentForm/MetricsPanel'
import { experimentWizardLogic } from '../experimentWizardLogic'

export function AnalyticsStep(): JSX.Element {
    const { experiment, sharedMetrics } = useValues(experimentWizardLogic)
    const { setExperiment, setExposureCriteria, setSharedMetrics } = useActions(experimentWizardLogic)

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
                    />
                </div>
            </div>

            <LemonBanner type="info">
                You can always add more metrics and refine your configuration after saving.
            </LemonBanner>
        </div>
    )
}
