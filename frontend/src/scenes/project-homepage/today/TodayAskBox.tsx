import { useActions } from 'kea'
import { ChangeEvent, useState } from 'react'

import { IconArrowRight } from '@posthog/icons'
import {
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

/** Sends the question to PostHog AI, which answers in a new tab. */
export function TodayAskBox(): JSX.Element {
    const { askSidePanelMax } = useActions(maxGlobalLogic)
    const [question, setQuestion] = useState('')
    const [sentQuestion, setSentQuestion] = useState<string | null>(null)

    return (
        <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
                event.preventDefault()
                const trimmed = question.trim()
                if (trimmed) {
                    askSidePanelMax(trimmed)
                    setSentQuestion(trimmed)
                    setQuestion('')
                }
            }}
        >
            <InputGroup>
                <InputGroupInput
                    value={question}
                    onChange={(event: ChangeEvent<HTMLInputElement>) => setQuestion(event.target.value)}
                    placeholder="What would you like to know?"
                    aria-label="Ask PostHog AI"
                    data-attr="today-ask-input"
                />
                <InputGroupAddon align="inline-end">
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <InputGroupButton
                                    type="submit"
                                    variant="primary"
                                    size="icon-sm"
                                    aria-label="Send question"
                                    disabled={!question.trim()}
                                    data-attr="today-ask-send"
                                />
                            }
                        >
                            <IconArrowRight />
                        </TooltipTrigger>
                        <TooltipContent>Send question</TooltipContent>
                    </Tooltip>
                </InputGroupAddon>
            </InputGroup>
            {sentQuestion && (
                <Text size="xs" variant="muted" className="truncate">{`Asked PostHog AI: “${sentQuestion}”`}</Text>
            )}
        </form>
    )
}
