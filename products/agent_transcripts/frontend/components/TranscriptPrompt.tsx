import { useId } from 'react'

import { IconCopy } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea, Label } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

export interface TranscriptPromptProps {
    prompt: string
    /** Called after the prompt reaches the clipboard. */
    onCopy: () => void
}

export function TranscriptPrompt({ prompt, onCopy }: TranscriptPromptProps): JSX.Element {
    const promptId = useId()

    const copyPrompt = (): void => {
        // copyToClipboard resolves false when the clipboard is unavailable or refuses the write, which is not a copy.
        void copyToClipboard(prompt, 'prompt').then((copied) => {
            if (copied) {
                onCopy()
            }
        })
    }

    return (
        <InputGroup>
            <InputGroupTextarea id={promptId} value={prompt} readOnly className="font-mono text-xs" />
            <InputGroupAddon align="block-start" className="border-b">
                <Label htmlFor={promptId}>Prompt</Label>
                <InputGroupButton
                    size="xs"
                    className="ml-auto"
                    onClick={copyPrompt}
                    data-attr="agent-transcript-copy-prompt"
                >
                    <IconCopy />
                    Copy prompt
                </InputGroupButton>
            </InputGroupAddon>
        </InputGroup>
    )
}
