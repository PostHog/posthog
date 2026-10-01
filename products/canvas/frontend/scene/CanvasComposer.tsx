import { ChangeEvent, KeyboardEvent, useRef } from 'react'

import { IconSend } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupTextarea,
    Item,
    ItemContent,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { CANVAS_GENERATE_SUGGESTIONS } from './canvasGenerateSuggestions'

export interface CanvasComposerProps {
    instruction: string
    onInstructionChange: (instruction: string, fromSuggestion: boolean) => void
    onSubmit: () => void
    /** True while the send is in flight. It blocks a second send. */
    submitting: boolean
    /** Why the prompt cannot be sent yet, or null when it can. */
    disabledReason: string | null
    /** Controls at the start of the composer's footer, such as the space picker. */
    footerStart?: JSX.Element
}

/** Describe a canvas and send it to the agent that builds it, with starter prompts below. */
export function CanvasComposer({
    instruction,
    onInstructionChange,
    onSubmit,
    submitting,
    disabledReason,
    footerStart,
}: CanvasComposerProps): JSX.Element {
    // quill's textarea does not forward refs, so focus goes through its form.
    const formRef = useRef<HTMLFormElement>(null)
    const focusComposer = (): void => formRef.current?.querySelector('textarea')?.focus()
    const submit = (): void => {
        if (!disabledReason && !submitting) {
            onSubmit()
        }
    }

    return (
        <div className="flex flex-col gap-4">
            <form
                ref={formRef}
                onSubmit={(event) => {
                    event.preventDefault()
                    submit()
                }}
            >
                <InputGroup>
                    <InputGroupTextarea
                        autoFocus
                        aria-label="Describe the canvas"
                        placeholder="A chart of daily signups for the last 30 days, with the total at the top"
                        rows={4}
                        value={instruction}
                        disabled={submitting}
                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                            onInstructionChange(event.target.value, false)
                        }
                        onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                                event.preventDefault()
                                submit()
                            }
                        }}
                        data-attr="canvas-generate-input"
                    />
                    <InputGroupAddon align="block-end" className="flex-wrap">
                        {footerStart}
                        <Tooltip>
                            <TooltipTrigger
                                delay={0}
                                render={
                                    <Button
                                        type="submit"
                                        variant="primary"
                                        size="icon-sm"
                                        className="ml-auto"
                                        aria-label="Build canvas"
                                        loading={submitting}
                                        disabled={!!disabledReason}
                                        data-attr="canvas-generate-submit"
                                    />
                                }
                            >
                                <IconSend />
                            </TooltipTrigger>
                            <TooltipContent>{disabledReason ?? 'Build canvas'}</TooltipContent>
                        </Tooltip>
                    </InputGroupAddon>
                </InputGroup>
            </form>
            <section aria-labelledby="canvas-suggestions-label" className="flex flex-col gap-2">
                <Text id="canvas-suggestions-label" size="xs" variant="muted" weight="medium" render={<h2 />}>
                    Start from an example
                </Text>
                <ItemGroup combined>
                    {CANVAS_GENERATE_SUGGESTIONS.map((suggestion) => (
                        <Item
                            key={suggestion.label}
                            variant="outline"
                            size="xs"
                            className="text-left hover:bg-fill-button-tertiary-hover"
                            render={
                                <button
                                    type="button"
                                    disabled={submitting}
                                    onClick={() => {
                                        onInstructionChange(suggestion.prompt, true)
                                        focusComposer()
                                    }}
                                    data-attr="canvas-generate-suggestion"
                                />
                            }
                        >
                            <ItemMedia aria-hidden>
                                <suggestion.icon />
                            </ItemMedia>
                            <ItemContent className="min-w-0">
                                <ItemTitle className="truncate">{suggestion.label}</ItemTitle>
                            </ItemContent>
                        </Item>
                    ))}
                </ItemGroup>
            </section>
        </div>
    )
}
