import { useActions, useValues } from 'kea'
import { useState } from 'react'

import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { IconEye } from '@posthog/icons'
import { LemonBanner, LemonCard, LemonSwitch } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { VisionDocsLink } from 'products/replay_vision/frontend/components/DocsLink'
import { DEFAULT_MODEL, OBSERVATION_CREDITS_BY_MODEL } from 'products/replay_vision/frontend/replay_scanners/types'
import { getReplayVisionEditDisabledReason } from 'products/replay_vision/frontend/utils/accessControl'
import { formatCredits } from 'products/replay_vision/frontend/utils/credits'

import { ExposureCriteriaPanel } from '../../ExperimentForm/ExposureCriteriaPanel'
import { MetricsPanel } from '../../ExperimentForm/MetricsPanel'
import { experimentWizardLogic } from '../experimentWizardLogic'

const HedgehogXRay = pngHoggie(xRayPng)

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

            <ReplayVisionScannerToggle />

            <LemonBanner type="info">
                You can always refine your analytics configuration and metrics after saving.
            </LemonBanner>
        </div>
    )
}

/** Turning this on opts the experiment into a Replay Vision scanner, created at save. The scanner
 * endpoint refuses without org AI approval, so turning it on without consent opens the consent popover
 * instead of letting the experiment save and the scanner fail after the fact. */
function ReplayVisionScannerToggle(): JSX.Element {
    const { createReplayVisionScanner } = useValues(experimentWizardLogic)
    const { setCreateReplayVisionScanner } = useActions(experimentWizardLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    const card = (
        <LemonCard hoverEffect={false} className="@container flex items-start gap-4 p-4">
            <HedgehogXRay className="hidden @md:block w-20 shrink-0" />
            <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                        <div className="flex items-center gap-1.5 font-semibold">
                            <IconEye
                                className="size-4 shrink-0"
                                style={{ color: 'var(--color-product-session-replay-light)' }}
                            />
                            Watch participant behavior with Replay Vision
                        </div>
                        <p className="m-0 mt-1 text-sm text-secondary">
                            AI watches the recordings of people in this experiment, so you don't have to. Every result
                            is an event you can query, graph, and alert on.
                        </p>
                    </div>
                    <LemonSwitch
                        checked={createReplayVisionScanner}
                        onChange={(checked) => {
                            if (checked && !dataProcessingAccepted) {
                                setConsentRequested(true)
                            } else {
                                setCreateReplayVisionScanner(checked)
                            }
                        }}
                        disabledReason={getReplayVisionEditDisabledReason() ?? undefined}
                        aria-label="Watch participant behavior with Replay Vision"
                        data-attr="experiment-create-replay-vision-scanner"
                    />
                </div>
                {/* Per-session price only: a monthly projection needs the 30-day recording history the
                 * estimate endpoint reads, and an unstarted experiment has no exposed sessions yet, so
                 * any monthly figure computed here would be a misleading zero. The scanner page shows
                 * the projection once participant sessions exist. Priced at the model
                 * experimentScannerBody pins, so this matches the scanner the save path creates. */}
                <p className="m-0 text-xs text-muted">
                    It's created turned off, so nothing is scanned until you turn it on. Each scanned session costs{' '}
                    {formatCredits(OBSERVATION_CREDITS_BY_MODEL[DEFAULT_MODEL])}.
                </p>
                <div className="text-sm">
                    <VisionDocsLink dataAttr="experiment-create-replay-vision-docs">
                        Learn more about Replay Vision
                    </VisionDocsLink>
                </div>
            </div>
        </LemonCard>
    )

    if (dataProcessingAccepted) {
        return card
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
            {card}
        </AIConsentPopoverWrapper>
    )
}
