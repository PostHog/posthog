import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonCheckbox } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { DEFAULT_MODEL, OBSERVATION_CREDITS_BY_MODEL } from 'products/replay_vision/frontend/replay_scanners/types'
import { getReplayVisionEditDisabledReason } from 'products/replay_vision/frontend/utils/accessControl'
import { formatCredits } from 'products/replay_vision/frontend/utils/credits'

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
                        onSaveExposureCriteria={setExposureCriteria}
                    />
                </div>
            </div>

            <ReplayVisionScannerCheckbox />

            <LemonBanner type="info">
                You can always refine your analytics configuration and metrics after saving.
            </LemonBanner>
        </div>
    )
}

/** Ticking this opts the experiment into a Replay Vision scanner, created at save. The scanner
 * endpoint refuses without org AI approval, so an unconsented tick opens the consent popover
 * instead of letting the experiment save and the scanner fail after the fact. */
function ReplayVisionScannerCheckbox(): JSX.Element {
    const { createReplayVisionScanner } = useValues(experimentWizardLogic)
    const { setCreateReplayVisionScanner } = useActions(experimentWizardLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    const checkbox = (
        <LemonCheckbox
            bordered
            fullWidth
            checked={createReplayVisionScanner}
            onChange={(checked) => {
                if (checked && !dataProcessingAccepted) {
                    setConsentRequested(true)
                } else {
                    setCreateReplayVisionScanner(checked)
                }
            }}
            disabledReason={getReplayVisionEditDisabledReason() ?? undefined}
            data-attr="experiment-create-replay-vision-scanner"
            label={
                <div className="py-3">
                    <div className="font-semibold">Watch participant behavior with Replay Vision</div>
                    <div className="mt-1 font-normal text-sm text-muted">
                        Set up a scanner that classifies what participants do after experiment exposure. It is created
                        turned off, so nothing is scanned and no credits are used until you turn it on. You can adjust
                        its prompt, filters, and sampling first. A scanner keeps running after the experiment ends, so
                        turn it off when you are done.
                    </div>
                    {/* Per-session price only: a monthly projection needs the 30-day recording history the
                     * estimate endpoint reads, and an unstarted experiment has no exposed sessions yet, so
                     * any monthly figure computed here would be a misleading zero. The scanner page shows
                     * the projection once participant sessions exist. Priced at the model
                     * experimentScannerBody pins, so this matches the scanner the save path creates. */}
                    <div className="font-normal text-sm text-muted mt-1">
                        Each scanned session costs {formatCredits(OBSERVATION_CREDITS_BY_MODEL[DEFAULT_MODEL])}. The
                        scanner shows a projected monthly cost once the experiment has participants.
                    </div>
                </div>
            }
        />
    )

    if (dataProcessingAccepted) {
        return checkbox
    }

    return (
        <AIConsentPopoverWrapper
            placement="top"
            showArrow
            ignoreDismissal
            hideTrainingDisclaimer
            hidden={!consentRequested}
            onApprove={() => {
                setConsentRequested(false)
                setCreateReplayVisionScanner(true)
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {checkbox}
        </AIConsentPopoverWrapper>
    )
}
