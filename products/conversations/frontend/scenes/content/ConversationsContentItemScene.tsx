import { LemonButton, LemonCard, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { LemonRichContentEditor } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import type { TicketChannel } from '../../data/tickets'

const mockContent = {
    id: 'cnt-001',
    title: 'Widget connection troubleshooting',
    enabled: true,
    content:
        'Common solutions for widget connectivity issues including CSP headers, firewall rules, and websocket configuration. Reference this when customers report connection problems.',
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
        <SceneContent>
            <SceneTitleSection
                name={mockContent.id}
                resourceType={{ type: 'conversation' }}
                description={`Last updated ${mockContent.updatedAt} by ${mockContent.updatedBy}`}
                forceBackTo={{
                    name: 'Content library',
                    path: urls.conversationsContent(),
                    key: 'conversationsContent',
                }}
                actions={<LemonButton type="secondary">{mockContent.enabled ? 'Disable' : 'Enable'}</LemonButton>}
            />

            <LemonCard hoverEffect={false} className="p-4 space-y-4">
                <div className="space-y-2">
                    <label className="text-sm font-medium">Name</label>
                    <LemonInput value={mockContent.title} placeholder="Article name" />
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Channels</label>
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
                    <label className="text-sm font-medium">Content</label>

                    <LemonRichContentEditor
                        minRows={8}
                        logicKey="content-editor"
                        placeholder="Write your knowledge base article here. Use formatting, links, and lists to structure the content. AI will reference and synthesize from this."
                    />
                </div>

                <div className="flex gap-2 justify-end">
                    <LemonButton type="primary">Save</LemonButton>
                </div>
            </LemonCard>
        </SceneContent>
    )
}
