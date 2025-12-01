import { IconX } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCheckbox, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import type { TicketChannel } from '../../data/tickets'

const mockGuidance = {
    id: 'guide-1',
    title: 'EU Compliance tone',
    enabled: true,
    tone: 'Professional and empathetic. Always acknowledge GDPR rights and data privacy concerns.',
    escalationRules: [
        { id: '1', rule: 'Escalate if customer mentions legal action or regulation violations', enabled: true },
        { id: '2', rule: 'Escalate if refund amount exceeds $5,000', enabled: true },
        { id: '3', rule: 'Escalate if customer requests to speak with manager', enabled: false },
    ],
    channels: [
        { key: 'widget' as TicketChannel, enabled: true },
        { key: 'slack' as TicketChannel, enabled: false },
        { key: 'email' as TicketChannel, enabled: true },
    ],
    updatedAt: 'Today • 14:22',
    updatedBy: 'Dana Hill',
}

export const scene: SceneExport = {
    component: ConversationsGuidanceItemScene,
}

export function ConversationsGuidanceItemScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name={mockGuidance.id}
                resourceType={{ type: 'conversation' }}
                description={`Last updated ${mockGuidance.updatedAt} by ${mockGuidance.updatedBy}`}
                forceBackTo={{
                    name: 'Guidance',
                    path: urls.conversationsGuidance(),
                    key: 'conversationsGuidance',
                }}
                actions={<LemonButton type="secondary">{mockGuidance.enabled ? 'Disable' : 'Enable'}</LemonButton>}
            />

            <LemonCard hoverEffect={false} className="p-4 space-y-4">
                <div className="space-y-2">
                    <label className="text-sm font-medium">Name</label>
                    <LemonInput value={mockGuidance.title} placeholder="Guidance name" />
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Channels</label>
                    <div className="space-y-2">
                        {mockGuidance.channels.map(({ key, enabled }) => (
                            <LemonCheckbox
                                key={key}
                                label={<ChannelsTag channel={key} />}
                                checked={enabled}
                                onChange={() => null}
                            />
                        ))}
                    </div>
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Tone & style</label>
                    <LemonTextArea
                        minRows={4}
                        value={mockGuidance.tone}
                        placeholder="Describe how the AI should communicate (e.g. professional, friendly, empathetic)"
                    />
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Escalation rules</label>
                    <p className="text-xs text-muted-alt">When should AI hand off to a human?</p>
                    <div className="space-y-2">
                        {mockGuidance.escalationRules.map((rule) => (
                            <div
                                key={rule.id}
                                className="flex items-start gap-2 p-2 rounded border hover:border-border-bold"
                            >
                                <LemonCheckbox checked={rule.enabled} onChange={() => null} />
                                <span className="text-sm flex-1">{rule.rule}</span>
                                <LemonButton
                                    icon={<IconX />}
                                    size="xsmall"
                                    type="secondary"
                                    status="danger"
                                    tooltip="Delete rule"
                                    onClick={() => null}
                                />
                            </div>
                        ))}
                        <LemonButton type="secondary" size="small" fullWidth>
                            Add escalation rule
                        </LemonButton>
                    </div>
                </div>

                <div className="flex gap-2 justify-end">
                    <LemonButton type="primary">Save</LemonButton>
                </div>
            </LemonCard>
        </SceneContent>
    )
}
