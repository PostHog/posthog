import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner, LemonCard, LemonCheckbox, LemonSelect, LemonSwitch, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { aiTriageTicketTypeLabel, TicketChannel } from '../../types'
import { supportSettingsLogic } from './supportSettingsLogic'

const CHANNEL_LABELS: Record<TicketChannel, string> = {
    widget: 'API / Widget',
    slack: 'Slack',
    email: 'Email',
    teams: 'Microsoft Teams',
    github: 'GitHub',
}

const CHANNEL_SETTINGS_TABS: Record<TicketChannel, string> = {
    widget: 'widget',
    slack: 'slack',
    email: 'email',
    teams: 'teams',
    github: 'github',
}

const TICKET_TYPES = ['how_to', 'diagnostic', 'account_billing'] as const

// Only how_to replies may be sent to the customer. diagnostic/account_billing draw on project
// data, so they're locked to private notes (enforced by the backend too).
const PUBLISHABLE_TICKET_TYPES = new Set<string>(['how_to'])

const REPLY_MODE_OPTIONS = [
    { value: 'private_note' as const, label: 'Private note' },
    { value: 'bot_reply' as const, label: 'AI reply' },
]

export function AISection(): JSX.Element {
    const {
        aiSuggestionsEnabled,
        aiSuggestionsLoading,
        aiDiagnosticsEnabled,
        aiDiagnosticsLoading,
        aiEnabledChannels,
        aiResolutionChannels,
        aiReplyModes,
    } = useValues(supportSettingsLogic)
    const { setAiSuggestionsEnabled, setAiDiagnosticsEnabled, setAiResolutionChannels, setAiReplyMode } =
        useActions(supportSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const businessKnowledgeEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE]
    const teamsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED]
    const githubEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_GITHUB_CHANNEL]

    const allChannels: TicketChannel[] = [
        'widget',
        'email',
        'slack',
        ...(teamsEnabled ? (['teams'] as const) : []),
        ...(githubEnabled ? (['github'] as const) : []),
    ]
    const isChannelActive = (channel: TicketChannel): boolean => aiEnabledChannels.includes(channel)

    const openChannelSettings = (channel: TicketChannel): void => {
        router.actions.push(urls.supportSettings(), router.values.searchParams, {
            selectedSetting: 'conversations-general',
            channel: CHANNEL_SETTINGS_TABS[channel],
        })
    }

    return (
        <>
            <SceneSection
                title="AI agent"
                className="my-8"
                description="When enabled, the AI agent automatically generates reply suggestions as private notes when new tickets arrive. Replies are grounded in your business knowledge sources."
            >
                <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Enable AI agent</label>
                            <p className="text-xs text-muted-alt mb-0">
                                Requires AI data processing consent at the organization level and at least one ready
                                business knowledge source.
                            </p>
                        </div>
                        <LemonSwitch
                            checked={aiSuggestionsEnabled}
                            onChange={(checked) => setAiSuggestionsEnabled(checked)}
                            loading={aiSuggestionsLoading}
                        />
                    </div>
                </LemonCard>
                {aiSuggestionsEnabled && businessKnowledgeEnabled && (
                    <LemonBanner type="info" className="max-w-[800px] mt-3">
                        Add your documents, links, and general context to{' '}
                        <Link to={urls.businessKnowledge()} target="_blank">
                            Business knowledge
                        </Link>{' '}
                        so the AI can ground its replies in your company's information.
                    </LemonBanner>
                )}
            </SceneSection>

            {aiSuggestionsEnabled && (
                <SceneSection
                    title="Investigate ticket data"
                    titleSize="sm"
                    className="my-8"
                    description="When enabled, tickets that report something broken let the agent query your project's data — events, error tracking, session recordings, and logs — to investigate the issue instead of relying on documentation alone. The agent has read-only access scoped to your project."
                >
                    <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                        <div className="flex items-center gap-4 justify-between">
                            <div>
                                <label className="font-medium">Allow the agent to investigate ticket data</label>
                                <p className="text-xs text-muted-alt mb-0">
                                    Leave this off to keep the agent grounded only in documentation and your business
                                    knowledge.
                                </p>
                            </div>
                            <LemonSwitch
                                checked={aiDiagnosticsEnabled}
                                onChange={(checked) => setAiDiagnosticsEnabled(checked)}
                                loading={aiDiagnosticsLoading}
                            />
                        </div>
                    </LemonCard>
                </SceneSection>
            )}

            {aiSuggestionsEnabled && (
                <SceneSection
                    title="Allowed channels"
                    titleSize="sm"
                    className="my-8"
                    description="Choose which channels the AI agent runs on. Inactive channels must be enabled under Channels first."
                >
                    <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                        {allChannels.map((channel) => {
                            const active = isChannelActive(channel)
                            return (
                                <LemonCheckbox
                                    key={channel}
                                    checked={active && aiResolutionChannels.includes(channel)}
                                    disabledReason={
                                        active ? undefined : 'Enable this channel in Channels settings first'
                                    }
                                    onChange={(checked) => {
                                        const next = checked
                                            ? [...aiResolutionChannels, channel]
                                            : aiResolutionChannels.filter((c) => c !== channel)
                                        setAiResolutionChannels(next)
                                    }}
                                    label={
                                        <span className="inline-flex flex-wrap items-center gap-x-1">
                                            {CHANNEL_LABELS[channel]}
                                            {!active && (
                                                <>
                                                    <span className="text-muted-alt">·</span>
                                                    <Link
                                                        onClick={(e) => {
                                                            e.preventDefault()
                                                            openChannelSettings(channel)
                                                        }}
                                                        to={urls.supportSettings()}
                                                    >
                                                        Enable in Channels first
                                                    </Link>
                                                </>
                                            )}
                                        </span>
                                    }
                                />
                            )
                        })}
                    </LemonCard>
                </SceneSection>
            )}

            {aiSuggestionsEnabled && aiResolutionChannels.length > 0 && (
                <SceneSection
                    title="Reply behavior"
                    titleSize="sm"
                    className="my-8"
                    description={
                        <>
                            For each channel and ticket type, choose whether the AI agent posts a private note (visible
                            only to your team) or sends a safety-reviewed reply directly to the customer.{' '}
                            <strong>Diagnostic</strong> and <strong>Account/Billing</strong> replies may include data
                            from your project, so they're always kept as private notes and can't be sent directly to the
                            customer.
                        </>
                    }
                >
                    <LemonCard hoverEffect={false} className="max-w-[800px] px-4 py-3">
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                                <thead>
                                    <tr>
                                        <th className="text-left py-1 pr-3 font-medium text-muted-alt">Channel</th>
                                        {TICKET_TYPES.map((tt) => (
                                            <th key={tt} className="text-left py-1 px-2 font-medium text-muted-alt">
                                                {aiTriageTicketTypeLabel[tt]}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {aiResolutionChannels.map((channel) => (
                                        <tr key={channel} className="border-t border-border">
                                            <td className="py-2 pr-3 font-medium">
                                                {CHANNEL_LABELS[channel] ?? channel}
                                            </td>
                                            {TICKET_TYPES.map((tt) =>
                                                PUBLISHABLE_TICKET_TYPES.has(tt) ? (
                                                    <td key={tt} className="py-2 px-2">
                                                        <LemonSelect
                                                            size="xsmall"
                                                            options={REPLY_MODE_OPTIONS}
                                                            value={aiReplyModes[channel]?.[tt] ?? 'private_note'}
                                                            onChange={(value) => setAiReplyMode(channel, tt, value)}
                                                        />
                                                    </td>
                                                ) : (
                                                    <td key={tt} className="py-2 px-2 text-muted-alt">
                                                        Private note
                                                    </td>
                                                )
                                            )}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </LemonCard>
                </SceneSection>
            )}
        </>
    )
}
