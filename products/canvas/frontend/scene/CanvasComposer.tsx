import { ChangeEvent, KeyboardEvent, useRef } from 'react'

import { IconSend } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupTextarea,
    Item,
    ItemContent,
    ItemDescription,
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
    placeholder?: string
    ariaLabel?: string
    submitLabel?: string
    rows?: number
    /** Starter prompts below the box. A composer that continues a run leaves them out. */
    showSuggestions?: boolean
    autoFocus?: boolean
    /** Prefix for the `-input` and `-submit` data-attr values. */
    dataAttr?: string
}

/** Describe a canvas or a change to it and send it to the agent. Enter sends, Shift+Enter adds a line. */
export function CanvasComposer({
    instruction,
    onInstructionChange,
    onSubmit,
    submitting,
    disabledReason,
    footerStart,
    placeholder = 'A chart of daily signups for the last 30 days, with the total at the top',
    ariaLabel = 'Describe the canvas',
    submitLabel = 'Build canvas',
    rows = 4,
    showSuggestions = true,
    autoFocus = true,
    dataAttr = 'canvas-generate',
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
                        autoFocus={autoFocus}
                        aria-label={ariaLabel}
                        placeholder={placeholder}
                        rows={rows}
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
                        data-attr={`${dataAttr}-input`}
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
                                        aria-label={submitLabel}
                                        loading={submitting}
                                        disabled={!!disabledReason}
                                        data-attr={`${dataAttr}-submit`}
                                    />
                                }
                            >
                                <IconSend />
                            </TooltipTrigger>
                            <TooltipContent>{disabledReason ?? submitLabel}</TooltipContent>
                        </Tooltip>
                    </InputGroupAddon>
                </InputGroup>
            </form>
            {showSuggestions && (
                <section aria-labelledby="canvas-suggestions-label" className="@container flex flex-col gap-2">
                    <Text id="canvas-suggestions-label" size="xs" variant="muted" weight="medium" render={<h2 />}>
                        Suggestions
                    </Text>
                    <div className="grid grid-cols-1 gap-2 @min-[32rem]:grid-cols-2">
                        {CANVAS_GENERATE_SUGGESTIONS.map((suggestion) => (
                            <Item
                                key={suggestion.label}
                                variant="outline"
                                size="sm"
                                className="flex-nowrap bg-card text-left hover:bg-fill-hover"
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
                                    <ItemDescription className="truncate">{suggestion.description}</ItemDescription>
                                </ItemContent>
                            </Item>
                        ))}
                    </div>
                </section>
            )}
        </div>
    )
}
