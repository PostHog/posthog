import { LemonButton, LemonCard, LemonCheckbox, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import type { TicketChannel } from '../../data/tickets'

const mockContent = {
    id: 'cnt-001',
    title: 'Cloudflare allowlist procedure',
    status: 'published',
    content:
        'Step-by-step procedure to unblock widget websocket connections when Cloudflare rules change. Include CSP, Cloudflare rules, and contact details.',
    audience: {
        geo: 'Germany, France',
        plan: 'Enterprise',
        segment: 'High ARR',
    },
    channels: [
        { key: 'widget' as TicketChannel, enabled: true },
        { key: 'slack' as TicketChannel, enabled: true },
        { key: 'email' as TicketChannel, enabled: false },
    ],
    updatedAt: 'Today • 09:22',
    updatedBy: 'Alex Rivera',
}

export const scene: SceneExport = {
    component: ConversationsContentItemScene,
}

export function ConversationsContentItemScene(): JSX.Element {
    return (
        <SceneContent className="space-y-5">
            <ScenesTabs />
            <SceneTitleSection
                name={`${mockContent.title} (${mockContent.id})`}
                resourceType={{ type: 'conversation' }}
                description={`Last updated ${mockContent.updatedAt} by ${mockContent.updatedBy}`}
                forceBackTo={{
                    name: 'Content library',
                    path: urls.conversationsContent(),
                    key: 'conversationsContent',
                }}
                actions={
                    <div className="flex gap-2">
                        <LemonButton type="secondary">
                            {mockContent.status === 'published' ? 'Unpublish' : 'Publish'}
                        </LemonButton>
                        <LemonButton type="primary">Save</LemonButton>
                    </div>
                }
            />

            <div className="grid gap-4 lg:grid-cols-3">
                <LemonCard hoverEffect={false} className="space-y-4 lg:col-span-2">
                    <LemonInput value={mockContent.title} placeholder="Title" />
                    <LemonTextArea minRows={8} value={mockContent.content} placeholder="Content text" />
                </LemonCard>

                <LemonCard hoverEffect={false} className="space-y-4">
                    <div className="space-y-2">
                        <h3 className="text-lg font-semibold">Channels</h3>
                        <div className="space-y-2">
                            {mockContent.channels.map(({ key, enabled }) => (
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
                        <h3 className="text-lg font-semibold">Audience</h3>
                        <div className="mt-2 space-y-2">
                            <label className="text-xs text-muted-alt block">Geo</label>
                            <LemonInput value={mockContent.audience.geo} placeholder="e.g. Germany, France" />
                        </div>
                        <div className="space-y-2">
                            <label className="text-xs text-muted-alt block">Segment</label>
                            <LemonInput value={mockContent.audience.segment} placeholder="e.g. High ARR" />
                        </div>
                    </div>
                </LemonCard>
            </div>
        </SceneContent>
    )
}
