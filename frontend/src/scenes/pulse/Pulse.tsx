import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPulse, IconRefresh, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { Error404 } from '~/layout/Error404'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { pulseLogic } from './pulseLogic'
import {
    PulseChannel,
    PulseDigestSummary,
    PulseFindingType,
    PulseSubscriptionFrequency,
    PulseSubscriptionType,
} from './pulseTypes'
import { formatSignedPct } from './utils'

export const scene: SceneExport = {
    component: Pulse,
    logic: pulseLogic,
}

const FREQUENCY_OPTIONS: { value: PulseSubscriptionFrequency; label: string }[] = [
    { value: 'weekly', label: 'Weekly' },
    { value: 'daily', label: 'Daily' },
]

const CHANNEL_OPTIONS: { value: PulseChannel; label: string }[] = [
    { value: 'in_app', label: 'In-app inbox' },
    { value: 'slack', label: 'Slack' },
    { value: 'email', label: 'Email' },
]

function FindingCard({ finding }: { finding: PulseFindingType }): JSX.Element {
    const { submitFeedback } = useActions(pulseLogic)
    const tagType = finding.change_pct >= 0 ? 'success' : 'danger'

    return (
        <div className="border rounded p-4 bg-surface-primary">
            <div className="flex items-center gap-2 mb-2">
                <h3 className="text-base font-semibold mb-0">{finding.metric_label}</h3>
                <LemonTag type={tagType}>{formatSignedPct(finding.change_pct)}</LemonTag>
                <span className="text-muted-alt text-xs">z = {finding.z_score.toFixed(1)}</span>
            </div>
            <p className="text-sm mb-3">{finding.narrative}</p>
            <div className="flex items-center gap-2">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconThumbsUp />}
                    onClick={() => submitFeedback(finding.id, 'up')}
                    active={finding.feedback === 'up'}
                >
                    Useful
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconThumbsDown />}
                    onClick={() => submitFeedback(finding.id, 'down')}
                    active={finding.feedback === 'down'}
                >
                    Not useful
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => submitFeedback(finding.id, 'dismissed')}
                    active={finding.feedback === 'dismissed'}
                >
                    Dismiss
                </LemonButton>
            </div>
        </div>
    )
}

function SubscriptionPanel(): JSX.Element {
    const { subscriptionDraft, subscriptionLoading } = useValues(pulseLogic) as {
        subscriptionDraft: PulseSubscriptionType | null
        subscriptionLoading: boolean
    }
    const { updateSubscriptionLocal, saveSubscription } = useActions(pulseLogic)

    if (subscriptionLoading || !subscriptionDraft) {
        return <Spinner />
    }

    const toggleChannel = (channel: PulseChannel): void => {
        const next = subscriptionDraft.enabled_channels.includes(channel)
            ? subscriptionDraft.enabled_channels.filter((c: PulseChannel) => c !== channel)
            : [...subscriptionDraft.enabled_channels, channel]
        updateSubscriptionLocal({ enabled_channels: next })
    }

    return (
        <div className="border rounded p-4 bg-surface-secondary mb-6">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-base font-semibold mb-0">Pulse settings</h3>
                <LemonButton type="primary" size="small" onClick={() => saveSubscription()}>
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
                    <LemonSelect<PulseSubscriptionFrequency>
                        value={subscriptionDraft.frequency}
                        onChange={(v) => v && updateSubscriptionLocal({ frequency: v })}
                        options={FREQUENCY_OPTIONS}
                    />
                </div>
                <div className="flex items-center justify-between">
                    <span>Delivery channels</span>
                    <div className="flex gap-2">
                        {CHANNEL_OPTIONS.map((opt) => (
                            <LemonButton
                                key={opt.value}
                                size="small"
                                type={
                                    subscriptionDraft.enabled_channels.includes(opt.value) ? 'primary' : 'secondary'
                                }
                                onClick={() => toggleChannel(opt.value)}
                            >
                                {opt.label}
                            </LemonButton>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

export function Pulse(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { digests, findings, digestsLoading, findingsLoading, shouldShowEmptyState, latestDigest } = useValues(
        pulseLogic
    ) as {
        digests: PulseDigestSummary[]
        findings: PulseFindingType[]
        digestsLoading: boolean
        findingsLoading: boolean
        shouldShowEmptyState: boolean
        latestDigest: PulseDigestSummary | null
    }
    const { loadDigests, loadFindings, loadSubscription } = useActions(pulseLogic)

    useEffect(() => {
        if (!featureFlags[FEATURE_FLAGS.MAX_PULSE]) {
            return
        }
        loadDigests()
        loadFindings()
        loadSubscription()
    }, [featureFlags, loadDigests, loadFindings, loadSubscription])

    if (!featureFlags[FEATURE_FLAGS.MAX_PULSE]) {
        return <Error404 />
    }

    const findingsForLatest = latestDigest
        ? findings.filter((f: PulseFindingType) => f.digest === latestDigest.id)
        : []

    return (
        <SceneContent>
            <SceneTitleSection
                name="Pulse"
                description="Max scans your metrics and surfaces changes worth investigating."
                resourceType={{ type: 'project', forceIcon: <IconPulse /> }}
                actions={
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
                }
            />

            <SubscriptionPanel />

            {digestsLoading ? (
                <div className="flex justify-center py-8">
                    <Spinner />
                </div>
            ) : shouldShowEmptyState ? (
                <div className="border rounded p-6 bg-surface-primary text-center">
                    <p className="text-muted">No Pulse digests yet</p>
                    <p className="text-muted-alt text-sm mb-0 mt-1">
                        Once Pulse runs its first scan, findings will appear here.
                    </p>
                </div>
            ) : (
                <div className="space-y-6">
                    {latestDigest && (
                        <div>
                            <div className="flex items-center gap-2 mb-3">
                                <h2 className="text-lg font-semibold mb-0">Latest digest</h2>
                                <LemonTag>{latestDigest.status}</LemonTag>
                                <span className="text-muted-alt text-xs">
                                    <TZLabel time={latestDigest.created_at} />
                                </span>
                            </div>
                            {findingsForLatest.length === 0 ? (
                                <p className="text-muted">No findings in the latest digest.</p>
                            ) : (
                                <div className="space-y-3">
                                    {findingsForLatest.map((finding: PulseFindingType) => (
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
                                {digests.slice(1).map((digest: PulseDigestSummary) => (
                                    <li key={digest.id} className="border rounded p-3 bg-surface-primary">
                                        <div className="flex items-center justify-between">
                                            <span className="font-medium">
                                                <TZLabel time={digest.created_at} />
                                            </span>
                                            <span className="text-muted-alt text-sm">
                                                {digest.finding_count} finding{digest.finding_count === 1 ? '' : 's'}
                                            </span>
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}
        </SceneContent>
    )
}

export default Pulse
