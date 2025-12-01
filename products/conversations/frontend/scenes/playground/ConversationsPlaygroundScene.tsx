import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { CommentComposer } from 'scenes/comments/CommentComposer'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ScenesTabs } from '../../components/ScenesTabs'

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
        role: 'Tester',
        timestamp: '09:14',
        content: 'Our widget keeps reconnecting on the EU pricing page—how should we respond?',
    },
    {
        id: 'msg-2',
        actor: 'ai',
        author: 'AI Copilot',
        role: 'Assistant',
        timestamp: '09:14',
        content:
            'Cloudflare is blocking the websocket endpoint. Ask the customer to add wss://web.posthog.com and *.posthog.com to the allowlist, then reload the page.',
    },
    {
        id: 'msg-3',
        actor: 'tester',
        author: 'You',
        role: 'Tester',
        timestamp: '09:15',
        content: 'What if they still see reconnects after the allowlist update?',
    },
    {
        id: 'msg-4',
        actor: 'ai',
        author: 'AI Copilot',
        role: 'Assistant',
        timestamp: '09:15',
        content:
            'Escalate to Tier 2 with the SLA tag "P1 Widget" if it persists beyond 5 minutes. I can draft the escalation note for you.',
    },
]

export const scene: SceneExport = {
    component: ConversationsPlaygroundScene,
}

export function ConversationsPlaygroundScene(): JSX.Element {
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
            <p className="text-muted-alt mb-4">
                Test how the AI responds with your current content and guidance. Send test prompts to preview answers
                before going live.
            </p>
            <div className="grid gap-4 lg:grid-cols-3">
                <div className="space-y-4 lg:col-span-2">
                    <LemonCard hoverEffect={false} className="flex flex-col overflow-hidden">
                        <div className="flex items-center justify-between p-3 border-b">
                            <span className="text-sm text-muted-alt">Chat with current content and guidance</span>
                            <LemonButton size="small" type="secondary">
                                Reset conversation
                            </LemonButton>
                        </div>
                        <div className="flex-1 overflow-y-auto p-4 space-y-1.5 min-h-[400px] max-h-[500px]">
                            {mockConversation.map((message) => (
                                <div
                                    key={message.id}
                                    className={`flex ${message.actor === 'tester' ? 'flex-row-reverse ml-10' : 'mr-10'}`}
                                >
                                    <div
                                        className={`flex flex-col min-w-0 ${message.actor === 'tester' ? 'items-end' : 'items-start'}`}
                                    >
                                        <div className="max-w-full">
                                            <div className="border py-2 px-3 rounded-lg bg-surface-primary">
                                                <div className="flex items-center gap-2 text-xs text-muted mb-1">
                                                    <span className="font-medium">{message.author}</span>
                                                    {message.role && (
                                                        <span className="text-muted-alt">· {message.role}</span>
                                                    )}
                                                    <span className="text-muted-alt">· {message.timestamp}</span>
                                                </div>
                                                <p className="text-sm">{message.content}</p>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div className="border-t p-3">
                            <CommentComposer scope="conversation_playground" item_id="playground-test" />
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
