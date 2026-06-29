import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonCheckbox, LemonSelect, LemonSwitch, Link } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { FEATURE_FLAGS } from '~/lib/constants'

import { aiTriageTicketTypeLabel } from '../../types'
import { supportSettingsLogic } from './supportSettingsLogic'

const CHANNEL_LABELS: Record<string, string> = {
    widget: 'API / Widget',
    slack: 'Slack',
    email: 'Email',
    teams: 'Microsoft Teams',
    github: 'GitHub',
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

    return (
        <SceneSection
            title="AI suggestions"
            className="my-8"
            description="When enabled, PostHog will automatically generate a suggested reply as a private note whenever a new ticket arrives. Suggestions are grounded in your business knowledge sources."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <LemonSwitch
                    checked={aiSuggestionsEnabled}
                    onChange={(checked) => setAiSuggestionsEnabled(checked)}
                    loading={aiSuggestionsLoading}
                    label="Allow AI suggestions"
                />
                <p className="text-xs text-muted-alt mb-0">
                    Requires AI data processing consent at the organization level and at least one ready business
                    knowledge source.
                </p>
            </LemonCard>
            {aiSuggestionsEnabled && businessKnowledgeEnabled && (
                <LemonBanner type="info" className="max-w-[800px]">
                    Add your documents, links, and general context to{' '}
                    <Link to={urls.businessKnowledge()} target="_blank">
                        Business knowledge
                    </Link>{' '}
                    so the AI can ground its replies in your company's information.
                </LemonBanner>
            )}
            {aiSuggestionsEnabled && (
                <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                    <LemonSwitch
                        checked={aiDiagnosticsEnabled}
                        onChange={(checked) => setAiDiagnosticsEnabled(checked)}
                        loading={aiDiagnosticsLoading}
                        disabledReason={!aiSuggestionsEnabled ? 'Enable AI suggestions first' : undefined}
                        label="Allow the agent to investigate ticket data"
                    />
                    <p className="text-xs text-muted-alt mb-0">
                        When enabled, tickets that report something broken let the agent query your project's data —
                        events, error tracking, session recordings, and logs — to investigate the issue instead of
                        relying on documentation alone. The agent has read-only access scoped to your project. Leave
                        this off to keep suggestions grounded only in documentation and your business knowledge.
                    </p>
                </LemonCard>
            )}
            {aiSuggestionsEnabled && aiEnabledChannels.length > 0 && (
                <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                    <h4 className="font-semibold text-sm mb-0">Allowed channels</h4>
                    <p className="text-xs text-muted-alt mb-0">
                        Choose which channels the AI resolution pipeline runs on. Unchecked channels will not receive AI
                        suggestions.
                    </p>
                    <div className="flex flex-col gap-y-2">
                        {aiEnabledChannels.map((channel) => (
                            <LemonCheckbox
                                key={channel}
                                checked={aiResolutionChannels.includes(channel)}
                                onChange={(checked) => {
                                    const next = checked
                                        ? [...aiResolutionChannels, channel]
                                        : aiResolutionChannels.filter((c) => c !== channel)
                                    setAiResolutionChannels(next)
                                }}
                                label={CHANNEL_LABELS[channel] ?? channel}
                            />
                        ))}
                    </div>
                </LemonCard>
            )}

            {aiSuggestionsEnabled && aiResolutionChannels.length > 0 && (
                <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                    <h4 className="font-semibold text-sm mb-0">Reply behavior</h4>
                    <p className="text-xs text-muted-alt mb-0">
                        For each channel and ticket type, choose whether the AI posts a private note (visible only to
                        your team) or sends a safety-reviewed reply directly to the customer.
                    </p>
                    <p className="text-xs text-muted-alt mb-0">
                        <strong>Diagnostic and Account/Billing</strong> replies may include data from your project, so
                        they're always kept as private notes and can't be sent directly to the customer.
                    </p>
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
                                        <td className="py-2 pr-3 font-medium">{CHANNEL_LABELS[channel] ?? channel}</td>
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
            )}
        </SceneSection>
    )
}
