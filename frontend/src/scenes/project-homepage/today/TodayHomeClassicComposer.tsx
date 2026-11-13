import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Composer, QuillComposerLayout, QuillComposerSendButton } from 'products/posthog_ai/frontend/api/composer'

import { todayHomeComposerLogic } from './todayHomeComposerLogic'

/** The home composer for people without PostHog AI 2.0: it has no task runtime, so sending opens a chat. */
export function TodayHomeClassicComposer(): JSX.Element {
    const { classicPrompt } = useValues(todayHomeComposerLogic)
    const { setClassicPrompt, classicChatStarted } = useActions(todayHomeComposerLogic)
    const groupRef = useRef<HTMLDivElement>(null)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    return (
        <Composer.Root
            value={classicPrompt}
            onChange={setClassicPrompt}
            onSubmit={() => classicChatStarted(classicPrompt)}
            textAreaRef={textAreaRef}
        >
            <QuillComposerLayout
                groupRef={groupRef}
                textAreaRef={textAreaRef}
                field={
                    <Composer.Field>
                        <Composer.Placeholder>Ask a question</Composer.Placeholder>
                        <Composer.Textarea data-attr="today-home-chat-input" />
                    </Composer.Field>
                }
                send={<QuillComposerSendButton data-attr="today-home-chat-send" />}
                singleRow
            />
        </Composer.Root>
    )
}
