import { useState } from 'react'

import { LemonButton, LemonCard, LemonDivider, LemonSelect, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

const scenarios = [
    { value: 'widget', label: 'Widget · EU visitor' },
    { value: 'slack', label: 'Slack connect · Tier 2' },
    { value: 'email', label: 'Email · high ARR' },
]

const mockTrace = [
    { phase: 'Refine query', detail: 'Detected Cloudflare mention, rewrote prompt accordingly' },
    { phase: 'Retrieve content', detail: '3 snippets pulled (Cloudflare allowlist, refund policy, tone guidance)' },
    { phase: 'Rerank', detail: 'Selected allowlist procedure because confidence 0.91' },
    { phase: 'Generate', detail: 'Drafted response with instructions to update allowlist' },
    { phase: 'Validate', detail: 'Fallback triggered because account flagged priority' },
]

export const scene: SceneExport = {
    component: ConversationsPlaygroundScene,
}

export function ConversationsPlaygroundScene(): JSX.Element {
    const [prompt, setPrompt] = useState('Our widget keeps reconnecting on the EU pricing page—how do we fix it?')
    return (
        <SceneContent className="space-y-5">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Playground</h1>
                <p className="text-muted-alt">
                    Test prompts, inspect retrieval traces, and compare content/guidance stacks before deploying.
                </p>
            </section>

            <div className="grid gap-4 lg:grid-cols-3">
                <LemonCard hoverEffect={false}>
                    <div className="flex flex-col gap-2">
                        <LemonSelect value="widget" options={scenarios} onChange={() => null} placeholder="Scenario" />
                        <LemonSelect
                            value="guidance-eu"
                            options={[
                                { value: 'guidance-eu', label: 'EU compliance tone' },
                                { value: 'guidance-us', label: 'US empathy' },
                            ]}
                            placeholder="Guidance pack"
                        />
                        <LemonSelect
                            value="content-set-a"
                            options={[
                                { value: 'content-set-a', label: 'Allowlist procedures + billing snippets' },
                                { value: 'content-set-b', label: 'General knowledge' },
                            ]}
                            placeholder="Content stack"
                        />
                    </div>
                </LemonCard>
                <LemonCard hoverEffect={false} className="lg:col-span-2">
                    <div className="flex justify-between">
                        <div>
                            <div className="text-sm text-muted-alt">Selected content</div>
                            <div className="flex gap-2 mt-1">
                                <LemonTag type="muted">Cloudflare allowlist</LemonTag>
                                <LemonTag type="muted">Refund escalation</LemonTag>
                            </div>
                        </div>
                        <LemonButton size="small" type="secondary">
                            Swap stack
                        </LemonButton>
                    </div>
                </LemonCard>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
                <LemonCard hoverEffect={false} className="lg:col-span-2 space-y-3">
                    <div className="flex justify-between items-center">
                        <h3 className="text-lg font-semibold">Prompt</h3>
                        <LemonButton size="small" type="secondary">
                            Load conversation
                        </LemonButton>
                    </div>
                    <LemonTextArea minRows={4} value={prompt} onChange={setPrompt} />
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary">Clear</LemonButton>
                        <LemonButton type="primary">Run test</LemonButton>
                    </div>
                    <LemonDivider />
                    <h3 className="text-lg font-semibold">AI response preview</h3>
                    <div className="rounded border border-light bg-bg-300 p-3 text-sm text-primary-alt min-h-[160px]">
                        Hi there! It looks like your Cloudflare rule “443-block-bot” is blocking websocket traffic. I’d
                        recommend updating the allowlist with *.posthog.com and wss://web.posthog.com. Here’s the
                        step-by-step procedure...
                    </div>
                </LemonCard>

                <LemonCard hoverEffect={false}>
                    <h3 className="text-lg font-semibold">Retrieval trace</h3>
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
        </SceneContent>
    )
}
