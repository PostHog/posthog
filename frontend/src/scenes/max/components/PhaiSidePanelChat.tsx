import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { runStreamLogic } from 'products/posthog_ai/frontend/api/logics'
import { Composer, ThreadView } from 'products/posthog_ai/frontend/api/primitives'

import { Intro } from '../Intro'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

/**
 * The new (sandbox) PostHog AI chat for the side panel: just the new composer + thread viewer, no tasks
 * list. The thread streams from `runStreamLogic` keyed by the conversation — mirroring the sandbox path in
 * `Thread.tsx` — and the logic-free `Composer` is wired to Max's conversation send (`askMax`). Must render
 * inside Max's `maxLogic` + `maxThreadLogic` binds (it reads/sends through them).
 */
export function PhaiSidePanelChat(): JSX.Element {
    const { threadVisible } = useValues(maxLogic)
    const { conversation, sandboxConversationKey, threadLoading, streamingActive } = useValues(maxThreadLogic)
    const { askMax } = useActions(maxThreadLogic)

    // Local draft so each keystroke is a cheap local re-render rather than a global kea dispatch — long
    // threads make per-keystroke store notifications expensive (see QuestionInput). `askMax` reads the
    // prompt directly, so kea's `question` doesn't need to hold the draft here.
    const [draft, setDraft] = useState('')

    const submit = (): void => {
        const prompt = draft.trim()
        if (!prompt) {
            return
        }
        askMax(prompt)
        setDraft('')
    }

    // Only bind the sandbox stream for a born-sandbox conversation; a legacy (langgraph) conversation has no
    // run to stream, so we show the intro and let the next message start a fresh sandbox run.
    const isSandboxThread = threadVisible && conversation?.agent_runtime === 'sandbox' && !!sandboxConversationKey

    return (
        <div className="@container/thread flex flex-col h-full min-h-0">
            {isSandboxThread ? (
                <BindLogic
                    logic={runStreamLogic}
                    props={{ streamKey: sandboxConversationKey, conversationId: sandboxConversationKey }}
                >
                    <ThreadView className="flex-1 min-h-0" listClassName="py-3" rowClassName="px-3" />
                </BindLogic>
            ) : (
                <div className="flex flex-1 min-h-0 flex-col items-center justify-center gap-3 px-3 overflow-y-auto">
                    <Intro />
                </div>
            )}
            <div className="border-t border-primary px-3 pb-3 pt-2">
                <div className="mx-auto w-full max-w-180">
                    <Composer.Root value={draft} onChange={setDraft} onSubmit={submit} loading={threadLoading}>
                        <Composer.Frame ringActive={!streamingActive}>
                            <Composer.Field>
                                <Composer.Placeholder>Ask PostHog AI…</Composer.Placeholder>
                                <Composer.Textarea data-attr="phai-sidepanel-composer" />
                            </Composer.Field>
                        </Composer.Frame>
                        <Composer.Submit data-attr="phai-sidepanel-send" />
                    </Composer.Root>
                </div>
            </div>
        </div>
    )
}
