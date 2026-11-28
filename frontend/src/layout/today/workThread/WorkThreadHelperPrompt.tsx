import { useActions } from 'kea'
import { useId, useRef } from 'react'

import { Button, Field, FieldLabel, Textarea, anchoredToast } from '@posthog/quill'

import type { WorkOptionApi, WorkStepApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { captureWorkPromptCopied } from './workThreadEvents'
import { workThreadLogic } from './workThreadLogic'
import { buildWorkPrompt } from './workThreadPrompt'

interface WorkThreadHelperPromptProps {
    thread: WorkThreadApi
    step: WorkStepApi
    option: WorkOptionApi
}

export function WorkThreadHelperPrompt({ thread, step, option }: WorkThreadHelperPromptProps): JSX.Element {
    const { setPromptShown } = useActions(workThreadLogic({ threadKey: thread.key }))
    const copyRef = useRef<HTMLButtonElement>(null)
    const areaRef = useRef<HTMLTextAreaElement>(null)
    const areaId = useId()
    const prompt = buildWorkPrompt(thread.name, option)

    const selectForManualCopy = (): void => {
        areaRef.current?.focus()
        areaRef.current?.select()
        anchoredToast({
            description: 'Text selected. Press Ctrl or Cmd + C to copy.',
            anchor: copyRef.current,
            side: 'top',
        })
        captureWorkPromptCopied(thread, step, option, 'selected')
    }

    // Safari only allows a clipboard write that starts inside the click handler, so the write is not deferred.
    const copy = (): void => {
        if (!navigator.clipboard) {
            selectForManualCopy()
            return
        }
        navigator.clipboard.writeText(prompt).then(() => {
            anchoredToast({ description: 'Copied!', anchor: copyRef.current, side: 'top' })
            captureWorkPromptCopied(thread, step, option, 'clipboard')
        }, selectForManualCopy)
    }

    return (
        <div className="flex flex-col gap-3" data-attr="work-thread-prompt">
            <Field>
                <FieldLabel htmlFor={areaId}>Prompt for your own agent</FieldLabel>
                <Textarea id={areaId} ref={areaRef} readOnly rows={9} value={prompt} />
            </Field>
            <div className="flex flex-wrap justify-end gap-2">
                <Button variant="outline" onClick={() => setPromptShown(false)} data-attr="work-thread-prompt-back">
                    Back
                </Button>
                <Button ref={copyRef} variant="primary" onClick={copy} data-attr="work-thread-prompt-copy">
                    Copy
                </Button>
            </div>
        </div>
    )
}
