import { useActions, useValues } from 'kea'
import { useState } from 'react'

import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { IconEye } from '@posthog/icons'
import { LemonBanner, LemonCard, LemonCheckbox, LemonSwitch } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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

            <ReplayVisionScannerOption />

            <LemonBanner type="info">
                You can always refine your analytics configuration and metrics after saving.
            </LemonBanner>
        </div>
    )
}

/** Turning this on opts the experiment into a Replay Vision scanner, created at save. The scanner
 * endpoint refuses without org AI approval, so turning it on without consent opens the consent popover
 * instead of letting the experiment save and the scanner fail after the fact.
 *
 * The `test` arm of EXPERIMENT_WIZARD_REPLAY_VISION_CARD shows it as a card with a toggle, `control` keeps the
 * checkbox. The flag is read here, at the end of the analytics step, so only people who see the option are
 * exposed. */
function ReplayVisionScannerOption(): JSX.Element {
    const { createReplayVisionScanner } = useValues(experimentWizardLogic)
    const { setCreateReplayVisionScanner } = useActions(experimentWizardLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [consentRequested, setConsentRequested] = useState(false)

    const optionProps: ReplayVisionScannerOptionProps = {
        checked: createReplayVisionScanner,
        onChange: (checked) => {
            if (checked && !dataProcessingAccepted) {
                setConsentRequested(true)
            } else {
                setCreateReplayVisionScanner(checked)
            }
        },
        disabledReason: getReplayVisionEditDisabledReason() ?? undefined,
        // Per-session price only: a monthly projection needs the 30-day recording history the
        // estimate endpoint reads, and an unstarted experiment has no exposed sessions yet, so
        // any monthly figure computed here would be a misleading zero. The scanner page shows
        // the projection once participant sessions exist. Priced at the model
        // experimentScannerBody pins, so this matches the scanner the save path creates.
        sessionPrice: formatCredits(OBSERVATION_CREDITS_BY_MODEL[DEFAULT_MODEL]),
    }

    const option =
        featureFlags[FEATURE_FLAGS.EXPERIMENT_WIZARD_REPLAY_VISION_CARD] === 'test' ? (
            <ReplayVisionScannerCard {...optionProps} />
        ) : (
            <ReplayVisionScannerCheckbox {...optionProps} />
        )

    if (dataProcessingAccepted) {
        return option
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
            {option}
        </AIConsentPopoverWrapper>
    )
}

interface ReplayVisionScannerOptionProps {
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string
    sessionPrice: string
}

function ReplayVisionScannerCard({
    checked,
    onChange,
    disabledReason,
    sessionPrice,
}: ReplayVisionScannerOptionProps): JSX.Element {
    return (
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
                        checked={checked}
                        onChange={onChange}
                        disabledReason={disabledReason}
                        aria-label="Watch participant behavior with Replay Vision"
                        data-attr="experiment-create-replay-vision-scanner"
                    />
                </div>
                <p className="m-0 text-xs text-muted">
                    It's created turned off, so nothing is scanned until you turn it on. Each scanned session costs{' '}
                    {sessionPrice}.
                </p>
                <div className="text-sm">
                    <VisionDocsLink dataAttr="experiment-create-replay-vision-docs">
                        Learn more about Replay Vision
                    </VisionDocsLink>
                </div>
            </div>
        </LemonCard>
    )
}

function ReplayVisionScannerCheckbox({
    checked,
    onChange,
    disabledReason,
    sessionPrice,
}: ReplayVisionScannerOptionProps): JSX.Element {
    return (
        <LemonCheckbox
            bordered
            fullWidth
            checked={checked}
            onChange={onChange}
            disabledReason={disabledReason}
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
                    <div className="font-normal text-sm text-muted mt-1">
                        Each scanned session costs {sessionPrice}. The scanner shows a projected monthly cost once the
                        experiment has participants.
                    </div>
                </div>
            }
        />
    )
}
