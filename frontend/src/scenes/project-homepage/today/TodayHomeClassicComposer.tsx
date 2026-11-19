import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { useModeChoices } from 'scenes/max/components/ModeSelector'
import { QuillContextPicker } from 'scenes/max/components/QuillContextPicker'
import { QuillModeMenu } from 'scenes/max/components/QuillModeMenu'
import { ContextTags } from 'scenes/max/Context'

import { Composer, QuillComposerLayout, QuillComposerSendButton } from 'products/posthog_ai/frontend/api/composer'

import { todayHomeClassicComposerLogic } from './todayHomeClassicComposerLogic'

/** The home composer for people without PostHog AI 2.0: it has no task runtime, so sending opens a chat. */
export function TodayHomeClassicComposer(): JSX.Element {
    const { prompt, mode } = useValues(todayHomeClassicComposerLogic)
    const { setPrompt, setMode, chatStarted } = useActions(todayHomeClassicComposerLogic)
    const modeChoices = useModeChoices(false)
    const groupRef = useRef<HTMLDivElement>(null)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    return (
        <div className="TodayHome__composer" data-attr="today-home-composer">
            <Composer.Root
                value={prompt}
                onChange={setPrompt}
                onSubmit={() => chatStarted(prompt)}
                textAreaRef={textAreaRef}
            >
                <QuillComposerLayout
                    groupRef={groupRef}
                    textAreaRef={textAreaRef}
                    chips={<ContextTags />}
                    field={
                        <Composer.Field>
                            <Composer.Placeholder>Ask a question</Composer.Placeholder>
                            <Composer.Textarea data-attr="today-home-chat-input" />
                        </Composer.Field>
                    }
                    controls={
                        <>
                            <QuillContextPicker />
                            <QuillModeMenu value={mode} sections={modeChoices} onChange={setMode} />
                        </>
                    }
                    send={<QuillComposerSendButton data-attr="today-home-chat-send" />}
                    singleRow
                />
            </Composer.Root>
        </div>
    )
}
