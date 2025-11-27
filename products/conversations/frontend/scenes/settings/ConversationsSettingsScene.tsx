import { LemonButton, LemonCard, LemonSelect, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

const channels = [
    { id: 'widget', name: 'Widget', status: 'enabled', ai: true, fallback: 'Escalate after 2 messages' },
    { id: 'slack', name: 'Slack connect', status: 'enabled', ai: true, fallback: 'Escalate immediately' },
    { id: 'email', name: 'Email', status: 'disabled', ai: false, fallback: 'Manual only' },
]

const slackWorkspaces = [
    { name: 'Tier 2 (shared)', channel: '#support-tier2', status: 'connected' },
    { name: 'Partner support', channel: '#partners', status: 'connected' },
]

export const scene: SceneExport = {
    component: ConversationsSettingsScene,
}

export function ConversationsSettingsScene(): JSX.Element {
    return (
        <SceneContent className="space-y-5">
            <ScenesTabs />
            <section className="space-y-1">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h1 className="text-2xl font-semibold">Conversations settings</h1>
                        <p className="text-muted-alt">
                            Wire up Slack connect, widget defaults, and AI assistance toggles per channel.
                        </p>
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary">Test widget</LemonButton>
                        <LemonButton type="primary">Save changes</LemonButton>
                    </div>
                </div>
            </section>

            <div className="grid gap-4 lg:grid-cols-2">
                <LemonCard hoverEffect={false}>
                    <div className="flex items-center justify-between">
                        <div>
                            <h3 className="text-lg font-semibold">Slack connect</h3>
                            <p className="text-sm text-muted-alt">Sync shared channels for escalation and replies.</p>
                        </div>
                        <LemonButton type="secondary">Connect Slack</LemonButton>
                    </div>
                    <div className="mt-3 space-y-2 text-sm">
                        {slackWorkspaces.map((ws) => (
                            <div
                                key={ws.channel}
                                className="flex justify-between items-center rounded border border-light px-3 py-2"
                            >
                                <div>
                                    <div className="font-medium">{ws.name}</div>
                                    <div className="text-muted-alt text-xs">{ws.channel}</div>
                                </div>
                                <LemonTag type="success">{ws.status}</LemonTag>
                            </div>
                        ))}
                    </div>
                </LemonCard>

                <LemonCard hoverEffect={false}>
                    <h3 className="text-lg font-semibold">Widget defaults</h3>
                    <div className="mt-3 space-y-2 text-sm">
                        <div className="flex justify-between items-center">
                            <span>Widget enabled</span>
                            <LemonSwitch checked onChange={() => null} />
                        </div>
                        <div className="flex justify-between items-center">
                            <span>Theme</span>
                            <LemonSelect
                                value="light"
                                options={[
                                    { label: 'Light', value: 'light' },
                                    { label: 'Dark', value: 'dark' },
                                ]}
                                onChange={() => null}
                            />
                        </div>
                        <div className="flex justify-between items-center">
                            <span>Greeting</span>
                            <LemonSelect
                                value="hello"
                                options={[
                                    { label: 'Default', value: 'hello' },
                                    { label: 'Custom', value: 'custom' },
                                ]}
                                onChange={() => null}
                            />
                        </div>
                    </div>
                </LemonCard>
            </div>

            <LemonCard hoverEffect={false}>
                <div className="flex items-center justify-between mb-3">
                    <div>
                        <h3 className="text-lg font-semibold">Channel policies</h3>
                        <p className="text-sm text-muted-alt">Toggle AI assistance and escalations per channel.</p>
                    </div>
                    <LemonButton type="secondary">Add channel</LemonButton>
                </div>
                <div className="space-y-2">
                    {channels.map((channel) => (
                        <div
                            key={channel.id}
                            className="rounded border border-light px-3 py-2 flex flex-wrap items-center gap-3"
                        >
                            <div className="flex-1">
                                <div className="font-medium">{channel.name}</div>
                                <div className="text-xs text-muted-alt">{channel.fallback}</div>
                            </div>
                            <LemonSwitch
                                checked={channel.status === 'enabled'}
                                onChange={() => null}
                                label="channel enabled"
                            />
                            <LemonSwitch checked={channel.ai} onChange={() => null} label="AI assistance" />
                            <LemonButton size="small" type="secondary">
                                Configure
                            </LemonButton>
                        </div>
                    ))}
                </div>
            </LemonCard>
        </SceneContent>
    )
}
