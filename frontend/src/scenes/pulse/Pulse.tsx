import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconChevronRight, IconPulse, IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonCard,
    LemonCollapse,
    LemonInput,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { pulseLogic } from './pulseLogic'
import { PulseDigestStatus, PulseDigestSummary, PulseFindingType, PulseSensitivity } from './pulseTypes'
import { SENSITIVITY_PRESETS, ROBUST_Z_TOOLTIP, buildMaxSeedPrompt, describeChange } from './utils'

export const scene: SceneExport = {
    component: Pulse,
    logic: pulseLogic,
}

const FREQUENCY_OPTIONS: { value: 'weekly' | 'daily'; label: string }[] = [
    { value: 'weekly', label: 'Weekly' },
    { value: 'daily', label: 'Daily' },
]

const SENSITIVITY_OPTIONS: { value: PulseSensitivity; label: string }[] = [
    { value: 'conservative', label: 'Conservative' },
    { value: 'balanced', label: 'Balanced' },
    { value: 'sensitive', label: 'Sensitive' },
    { value: 'custom', label: 'Custom' },
]

const STATUS_TONES: Record<PulseDigestStatus, LemonTagType> = {
    delivered: 'success',
    failed: 'danger',
    generating: 'default',
    pending: 'default',
}

function statusTone(status: PulseDigestStatus): LemonTagType {
    return STATUS_TONES[status] ?? 'default'
}

function FindingCard({ finding }: { finding: PulseFindingType }): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const change = describeChange(finding.change_pct)
    const askMax = (): void => openSidePanel(SidePanelTab.Max, `!${buildMaxSeedPrompt(finding)}`)

    return (
        <LemonCard>
            <div className="flex items-center gap-2 mb-2">
                <h3 className="text-base font-semibold mb-0">{finding.metric_label}</h3>
                <LemonTag type={change.tone}>{change.label}</LemonTag>
                <Tooltip title={ROBUST_Z_TOOLTIP}>
                    <span className="text-muted-alt text-xs cursor-help">Why flagged?</span>
                </Tooltip>
                <div className="ml-auto flex items-center gap-1">
                    {finding.metric_descriptor?.url ? (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            to={finding.metric_descriptor.url as string}
                            targetBlank
                        >
                            View insight
                        </LemonButton>
                    ) : null}
                    <AIConsentPopoverWrapper onApprove={askMax}>
                        <LemonButton type="tertiary" size="xsmall" onClick={askMax} sideIcon={null}>
                            Ask Max why
                        </LemonButton>
                    </AIConsentPopoverWrapper>
                </div>
            </div>
            <p className="text-sm mb-0">{finding.narrative}</p>
            {finding.evidence?.session_ids?.length ? (
                <div className="flex items-center flex-wrap gap-2 mt-2 text-xs">
                    <span className="text-muted-alt">Example sessions:</span>
                    {finding.evidence.session_ids.map((sessionId, index) => (
                        <LemonButton
                            key={sessionId}
                            type="tertiary"
                            size="xsmall"
                            to={urls.replaySingle(sessionId)}
                            targetBlank
                        >
                            Replay {index + 1}
                        </LemonButton>
                    ))}
                </div>
            ) : null}
        </LemonCard>
    )
}

function SubscriptionPanel(): JSX.Element {
    const { subscriptionDraft, subscriptionLoading } = useValues(pulseLogic)
    const { updateSubscriptionLocal, saveSubscription } = useActions(pulseLogic)

    if (!subscriptionDraft) {
        return <LemonSkeleton className="h-40 w-full mb-6" />
    }

    const setSensitivity = (sensitivity: PulseSensitivity): void => {
        if (sensitivity === 'custom') {
            updateSubscriptionLocal({ sensitivity })
            return
        }
        updateSubscriptionLocal({ sensitivity, ...SENSITIVITY_PRESETS[sensitivity] })
    }

    return (
        <LemonCard className="mb-6">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-base font-semibold mb-0">Pulse settings</h3>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => saveSubscription()}
                    loading={subscriptionLoading}
                    disabledReason={subscriptionLoading ? 'Saving…' : undefined}
                >
                    Save settings
                </LemonButton>
            </div>
            <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                    <span>Enable Pulse</span>
                    <LemonSwitch
                        checked={subscriptionDraft.enabled}
                        onChange={(checked) => updateSubscriptionLocal({ enabled: checked })}
                    />
                </div>
                <div className="flex items-center justify-between">
                    <span>Frequency</span>
                    <LemonSelect
                        value={subscriptionDraft.frequency}
                        onChange={(v) => v && updateSubscriptionLocal({ frequency: v })}
                        options={FREQUENCY_OPTIONS}
                    />
                </div>
                <div className="flex items-center justify-between">
                    <span>Sensitivity</span>
                    <LemonSegmentedButton
                        value={subscriptionDraft.sensitivity}
                        onChange={(v) => setSensitivity(v)}
                        options={SENSITIVITY_OPTIONS}
                        size="small"
                    />
                </div>
                <LemonCollapse
                    panels={[
                        {
                            key: 'advanced',
                            header: 'Advanced',
                            content: (
                                <div className="flex flex-col gap-3">
                                    <div className="flex items-center justify-between">
                                        <span>Minimum change %</span>
                                        <LemonInput
                                            type="number"
                                            step={0.05}
                                            value={subscriptionDraft.min_change_pct}
                                            onChange={(v) =>
                                                updateSubscriptionLocal({
                                                    min_change_pct: v ?? 0,
                                                    sensitivity: 'custom',
                                                })
                                            }
                                        />
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span>Baseline weeks</span>
                                        <LemonInput
                                            type="number"
                                            value={subscriptionDraft.baseline_weeks}
                                            onChange={(v) => updateSubscriptionLocal({ baseline_weeks: v ?? 4 })}
                                        />
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span>Max findings</span>
                                        <LemonInput
                                            type="number"
                                            value={subscriptionDraft.max_findings}
                                            onChange={(v) => updateSubscriptionLocal({ max_findings: v ?? 5 })}
                                        />
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span>Robust z threshold</span>
                                        <LemonInput
                                            type="number"
                                            step={0.5}
                                            value={subscriptionDraft.robust_z_threshold}
                                            onChange={(v) =>
                                                updateSubscriptionLocal({
                                                    robust_z_threshold: v ?? 3.5,
                                                    sensitivity: 'custom',
                                                })
                                            }
                                        />
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonCard>
    )
}

function WatchedPanel(): JSX.Element | null {
    const { watchedCandidates, watchedCandidatesLoading } = useValues(pulseLogic)

    if (watchedCandidatesLoading) {
        return <LemonSkeleton className="h-24 w-full mb-6" />
    }
    if (!watchedCandidates.length) {
        return null
    }

    return (
        <LemonCard className="mb-6">
            <h3 className="text-base font-semibold mb-2">What Max is watching</h3>
            <p className="text-muted-alt text-sm mb-3">These metrics are scanned each cycle for notable changes.</p>
            <div className="flex flex-wrap gap-2">
                {watchedCandidates.map((c, i) => (
                    <LemonTag key={c.source_id ?? `${c.source}-${i}`} type="muted">
                        {c.label}
                    </LemonTag>
                ))}
            </div>
        </LemonCard>
    )
}

function DigestRow({ digest }: { digest: PulseDigestSummary }): JSX.Element {
    const { expandedDigestId, expandedDigest, expandedDigestLoading } = useValues(pulseLogic)
    const { setExpandedDigestId, getDigest } = useActions(pulseLogic)
    const isExpanded = expandedDigestId === digest.id

    const onToggle = (): void => {
        if (isExpanded) {
            setExpandedDigestId(null)
            return
        }
        setExpandedDigestId(digest.id)
        getDigest(digest.id)
    }

    return (
        <li className="border rounded bg-surface-primary">
            <button
                type="button"
                className="w-full flex items-center justify-between p-3 cursor-pointer bg-transparent border-none text-left"
                onClick={onToggle}
                aria-expanded={isExpanded}
            >
                <span className="flex items-center gap-2 font-medium">
                    <IconChevronRight
                        className={isExpanded ? 'rotate-90 transition-transform' : 'transition-transform'}
                    />
                    <TZLabel time={digest.created_at} />
                    <LemonTag type={statusTone(digest.status)}>{digest.status}</LemonTag>
                </span>
                <span className="text-muted-alt text-sm">
                    {digest.finding_count} finding{digest.finding_count === 1 ? '' : 's'}
                </span>
            </button>
            {isExpanded && (
                <div className="p-3 pt-0 space-y-3">
                    {digest.status === 'failed' ? (
                        <LemonBanner type="error">
                            <span className="font-semibold">Scan failed: </span>
                            {digest.error?.message ?? 'Unknown error'}
                        </LemonBanner>
                    ) : null}
                    {expandedDigestLoading || expandedDigest?.id !== digest.id ? (
                        <LemonSkeleton className="h-24 w-full" />
                    ) : expandedDigest.findings.length === 0 ? (
                        <p className="text-muted mb-0">No findings in this digest.</p>
                    ) : (
                        expandedDigest.findings.map((finding) => <FindingCard key={finding.id} finding={finding} />)
                    )}
                </div>
            )}
        </li>
    )
}

export function Pulse(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        digests,
        digestsLoading,
        findingsLoading,
        shouldShowEmptyState,
        latestDigest,
        findingsForLatest,
        digestsError,
        findingsError,
        scanTriggerLoading,
        isScanInProgress,
    } = useValues(pulseLogic)
    const { loadDigests, loadFindings, loadSubscription, loadWatched, triggerScan } = useActions(pulseLogic)
    const { user } = useValues(userLogic)

    const flagEnabled = !!featureFlags[FEATURE_FLAGS.MAX_PULSE]

    useEffect(() => {
        if (!flagEnabled) {
            return
        }
        loadDigests()
        loadFindings()
        loadSubscription()
        loadWatched()
    }, [flagEnabled, loadDigests, loadFindings, loadSubscription, loadWatched])

    if (!flagEnabled) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Pulse"
                    description="Max scans your metrics and surfaces changes worth investigating."
                    resourceType={{ type: 'project', forceIcon: <IconPulse /> }}
                />
                <ProductIntroduction
                    productName="Pulse"
                    thingName="finding"
                    description="Max scans your metrics each cycle and surfaces notable changes worth investigating. Pulse is rolling out gradually."
                    isEmpty
                    docsURL="https://posthog.com/docs"
                />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Pulse"
                description="Max scans your metrics and surfaces changes worth investigating."
                resourceType={{ type: 'project', forceIcon: <IconPulse /> }}
                actions={
                    <>
                        {user?.is_staff && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPulse />}
                                onClick={() => triggerScan()}
                                loading={scanTriggerLoading}
                                tooltip="Staff only: run a Pulse scan for this project now"
                            >
                                Run scan now
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            onClick={() => {
                                loadDigests()
                                loadFindings()
                            }}
                            loading={digestsLoading || findingsLoading}
                        >
                            Refresh
                        </LemonButton>
                    </>
                }
            />

            <SubscriptionPanel />
            <WatchedPanel />

            {digestsError && (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadDigests() }} className="mb-4">
                    Failed to load Pulse digests.
                </LemonBanner>
            )}
            {findingsError && (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => loadFindings() }}
                    className="mb-4"
                >
                    Failed to load findings.
                </LemonBanner>
            )}

            {isScanInProgress && (
                <LemonBanner type="info" className="mb-4">
                    <span className="flex items-center gap-2">
                        <Spinner />
                        Scan in progress — findings will appear here as soon as it finishes…
                    </span>
                </LemonBanner>
            )}

            {digestsLoading ? (
                <div className="space-y-3">
                    <LemonSkeleton className="h-8 w-48" />
                    <LemonSkeleton className="h-32 w-full" />
                    <LemonSkeleton className="h-32 w-full" />
                </div>
            ) : (
                <>
                    <ProductIntroduction
                        productName="Pulse"
                        thingName="finding"
                        description="Once Pulse runs its first scan, findings will appear here."
                        isEmpty={shouldShowEmptyState}
                        docsURL="https://posthog.com/docs"
                    />
                    {!shouldShowEmptyState && (
                        <div className="space-y-6">
                            {latestDigest && (
                                <div>
                                    <div className="flex items-center gap-2 mb-3">
                                        <h2 className="text-lg font-semibold mb-0">Latest digest</h2>
                                        <LemonTag type={statusTone(latestDigest.status)}>
                                            {latestDigest.status}
                                        </LemonTag>
                                        <span className="text-muted-alt text-xs">
                                            <TZLabel time={latestDigest.created_at} />
                                        </span>
                                    </div>
                                    {latestDigest.status === 'failed' ? (
                                        <LemonBanner type="error" className="mb-3">
                                            <span className="font-semibold">Scan failed: </span>
                                            {latestDigest.error?.message ?? 'Unknown error'}
                                        </LemonBanner>
                                    ) : null}
                                    {latestDigest.summary ? (
                                        <LemonBanner type="info" className="mb-3">
                                            <span className="font-semibold">Max's read: </span>
                                            {latestDigest.summary}
                                        </LemonBanner>
                                    ) : null}
                                    {findingsForLatest.length === 0 ? (
                                        <p className="text-muted">No findings in the latest digest.</p>
                                    ) : (
                                        <div className="grid grid-cols-1 gap-3">
                                            {findingsForLatest.map((finding) => (
                                                <FindingCard key={finding.id} finding={finding} />
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {digests.length > 1 && (
                                <div>
                                    <h2 className="text-lg font-semibold mb-3">Previous digests</h2>
                                    <ul className="space-y-2">
                                        {digests.slice(1).map((digest) => (
                                            <DigestRow key={digest.id} digest={digest} />
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </SceneContent>
    )
}

export default Pulse
