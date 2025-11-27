import { useState } from 'react'

import { LemonButton, LemonCard, LemonDivider, LemonSelect, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ScenesTabs } from '../../components/ScenesTabs'

const channelOptions = [
    { value: 'widget', label: 'Widget' },
    { value: 'slack', label: 'Slack connect' },
    { value: 'email', label: 'Email' },
]

const personaOptions = [
    { value: 'enterprise', label: 'Enterprise admin' },
    { value: 'founder', label: 'Founder' },
    { value: 'self-serve', label: 'Self-serve trial' },
]

const languageOptions = [
    { value: 'en', label: 'English' },
    { value: 'de', label: 'German' },
    { value: 'fr', label: 'French' },
]

const mockTrace = [
    { phase: 'Detect intent', detail: 'Matched “widget reconnecting” intent with score 0.93' },
    { phase: 'Retrieve content', detail: 'Cloudflare allowlist, SLA policy, tone pack pulled' },
    { phase: 'Rerank', detail: 'Allowlist procedure outranked general networking FAQ' },
    { phase: 'Generate reply', detail: 'Drafted fix instructions with escalation warning' },
    { phase: 'Validate', detail: 'Confidence 0.88 > containment threshold 0.8 → stay with AI' },
]

const mockConversation = [
    {
        id: 'msg-1',
        actor: 'tester',
        author: 'You',
        timestamp: '09:14',
        content: 'Our widget keeps reconnecting on the EU pricing page—how should we respond?',
    },
    {
        id: 'msg-2',
        actor: 'ai',
        author: 'Copilot',
        timestamp: '09:14',
        content:
            'Cloudflare is blocking the websocket endpoint. Ask the customer to add wss://web.posthog.com and *.posthog.com to the allowlist, then reload the page.',
    },
    {
        id: 'msg-3',
        actor: 'tester',
        author: 'You',
        timestamp: '09:15',
        content: 'What if they still see reconnects after the allowlist update?',
    },
    {
        id: 'msg-4',
        actor: 'ai',
        author: 'Copilot',
        timestamp: '09:15',
        content:
            'Escalate to Tier 2 with the SLA tag “P1 Widget” if it persists beyond 5 minutes. I can draft the escalation note for you.',
    },
]

const actorAccent: Record<'tester' | 'ai', string> = {
    tester: 'bg-side',
    ai: 'bg-success-highlight',
}

export const scene: SceneExport = {
    component: ConversationsPlaygroundScene,
}

export function ConversationsPlaygroundScene(): JSX.Element {
    const [channel, setChannel] = useState(channelOptions[0].value)
    const [persona, setPersona] = useState(personaOptions[0].value)
    const [language, setLanguage] = useState(languageOptions[0].value)
    const [draftMessage, setDraftMessage] = useState('Need to confirm Cloudflare steps before shipping to the queue.')

    return (
        <SceneContent>
            <SceneTitleSection
                name="Conversations"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-4 lg:col-span-2">
                    <LemonCard hoverEffect={false} className="space-y-4">
                        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-alt">
                            <span>
                                Configure the scenario, then chat to see how the AI responds with current content +
                                guardrails.
                            </span>
                            <LemonButton size="small" type="secondary">
                                Reset conversation
                            </LemonButton>
                        </div>
                        <div className="grid gap-3 md:grid-cols-3">
                            <div>
                                <div className="text-xs uppercase text-muted-alt">Channel</div>
                                <LemonSelect
                                    value={channel}
                                    onChange={(value) => value && setChannel(value)}
                                    options={channelOptions}
                                />
                            </div>
                            <div>
                                <div className="text-xs uppercase text-muted-alt">Persona</div>
                                <LemonSelect
                                    value={persona}
                                    onChange={(value) => value && setPersona(value)}
                                    options={personaOptions}
                                />
                            </div>
                            <div>
                                <div className="text-xs uppercase text-muted-alt">Language</div>
                                <LemonSelect
                                    value={language}
                                    onChange={(value) => value && setLanguage(value)}
                                    options={languageOptions}
                                />
                            </div>
                        </div>
                        <LemonDivider dashed />
                        <div className="space-y-3 rounded border border-light bg-bg-300 p-3 max-h-[420px] overflow-y-auto">
                            {mockConversation.map((message, index) => (
                                <div key={message.id}>
                                    <div
                                        className={`rounded px-3 py-2 ${actorAccent[message.actor as 'tester' | 'ai']} ${
                                            message.actor === 'tester' ? 'border border-primary' : ''
                                        }`}
                                    >
                                        <div className="flex items-center gap-2 text-sm font-medium">
                                            <span>{message.author}</span>
                                            <span className="text-xs text-muted-alt">{message.timestamp}</span>
                                            {message.actor === 'ai' && <LemonTag type="success">AI</LemonTag>}
                                        </div>
                                        <p className="mt-1 text-sm text-primary-alt">{message.content}</p>
                                    </div>
                                    {index < mockConversation.length - 1 && <LemonDivider dashed className="my-3" />}
                                </div>
                            ))}
                        </div>
                        <div className="space-y-2">
                            <div className="text-xs uppercase text-muted-alt">Send a test prompt</div>
                            <LemonTextArea minRows={3} value={draftMessage} onChange={setDraftMessage} />
                        </div>
                        <div className="flex justify-end gap-2">
                            <LemonButton type="secondary">Clear</LemonButton>
                            <LemonButton type="primary">Send to AI</LemonButton>
                        </div>
                    </LemonCard>
                </div>

                <div className="space-y-4">
                    <LemonCard hoverEffect={false}>
                        <div className="flex items-center justify-between">
                            <h3 className="text-lg font-semibold">Retrieval trace</h3>
                            <LemonTag type="muted">5 steps</LemonTag>
                        </div>
                        <div className="mt-3 space-y-2 text-sm">
                            {mockTrace.map((step) => (
                                <div key={step.phase} className="rounded border border-light px-3 py-2">
                                    <div className="text-xs text-muted-alt uppercase">{step.phase}</div>
                                    <div>{step.detail}</div>
                                </div>
                            ))}
                        </div>
                    </LemonCard>
                </div>
            </div>
        </SceneContent>
    )
}
