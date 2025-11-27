import { LemonButton, LemonCard, LemonInput, LemonSegmentedButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ScenesTabs } from '../../components/ScenesTabs'

const mockContent = {
    id: 'cnt-001',
    title: 'Cloudflare allowlist procedure',
    type: 'Procedure',
    status: 'published',
    summary: 'Step-by-step procedure to unblock widget websocket connections when Cloudflare rules change.',
    content: `1. Navigate to Cloudflare firewall rules
2. Search for rule "443-block-bot" and duplicate
3. Add *.posthog.com and wss://web.posthog.com to allowlist
4. Confirm widget reconnects on EU staging site
5. Notify customer with links to allowlist instructions`,
    targeting: {
        geo: ['Germany', 'France'],
        plan: ['Enterprise'],
        segment: ['High ARR'],
    },
    channels: ['widget', 'slack'],
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
                        <LemonButton type="secondary">Preview</LemonButton>
                        <LemonButton type="primary">Save</LemonButton>
                    </div>
                }
            />

            <div className="grid gap-4 lg:grid-cols-3">
                <LemonCard hoverEffect={false} className="lg:col-span-2 space-y-4">
                    <div className="flex flex-wrap items-center gap-3">
                        <LemonInput className="flex-1" value={mockContent.title} />
                        <LemonSegmentedButton
                            value={mockContent.status}
                            options={[
                                { label: 'Draft', value: 'draft' },
                                { label: 'Published', value: 'published' },
                            ]}
                            onChange={() => null}
                        />
                    </div>
                    <LemonInput value={mockContent.summary} placeholder="Summary" />
                    <LemonTextArea minRows={10} value={mockContent.content} />
                    <div className="flex justify-between items-center">
                        <div className="text-xs text-muted-alt">
                            Autosaved just now • <span className="text-primary">View version history</span>
                        </div>
                        <div className="flex gap-2">
                            <LemonButton type="secondary">Discard</LemonButton>
                            <LemonButton type="primary">Publish</LemonButton>
                        </div>
                    </div>
                </LemonCard>

                <div className="space-y-4">
                    <LemonCard hoverEffect={false}>
                        <h3 className="text-lg font-semibold">Targeting</h3>
                        <div className="mt-3 space-y-2 text-sm">
                            <div className="flex justify-between">
                                <span>Geo</span>
                                <span>Germany, France</span>
                            </div>
                            <div className="flex justify-between">
                                <span>Plan</span>
                                <span>Enterprise</span>
                            </div>
                            <div className="flex justify-between">
                                <span>Segment</span>
                                <span>High ARR</span>
                            </div>
                        </div>
                        <div className="mt-3 flex gap-2">
                            <LemonButton type="secondary" size="small">
                                Edit targeting
                            </LemonButton>
                            <LemonButton type="secondary" size="small">
                                Duplicate targeting
                            </LemonButton>
                        </div>
                    </LemonCard>

                    <LemonCard hoverEffect={false}>
                        <h3 className="text-lg font-semibold">Channels</h3>
                        <p className="text-sm text-muted-alt">Where this content can be referenced.</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                            {mockContent.channels.map((channel) => (
                                <LemonTag key={channel} type="muted">
                                    {channel}
                                </LemonTag>
                            ))}
                        </div>
                        <LemonButton className="mt-3 w-full" type="secondary">
                            Manage sync
                        </LemonButton>
                    </LemonCard>
                </div>
            </div>
        </SceneContent>
    )
}
