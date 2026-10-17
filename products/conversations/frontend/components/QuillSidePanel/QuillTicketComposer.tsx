import { JSONContent } from '@tiptap/core'
import { useRef, useState } from 'react'

import { Button, Kbd, KbdGroup, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import { SupportEditor, serializeToMarkdown } from '../Editor'

interface QuillTicketComposerProps {
    /** Sends the message as Markdown. Call `onSuccess` once it lands so the composer clears. */
    onSend: (content: string, onSuccess: () => void) => void
    sending: boolean
    placeholder?: string
    buttonText?: string
    minRows?: number
    /** Seeds the editor once at mount, e.g. from a prefilled "Contact support" call to action. */
    draftContent?: JSONContent | string | null
    autoFocus?: boolean
}

/**
 * The customer's composer for a support ticket. The rich editor stays, so people can still paste screenshots and
 * format code, and the frame and send controls are quill.
 */
export function QuillTicketComposer({
    onSend,
    sending,
    placeholder,
    buttonText = 'Send',
    minRows = 3,
    draftContent,
    autoFocus = false,
}: QuillTicketComposerProps): JSX.Element {
    const editorRef = useRef<RichContentEditorType | null>(null)
    const [isEmpty, setIsEmpty] = useState(!draftContent)
    const [isUploading, setIsUploading] = useState(false)

    const blockedReason = isEmpty ? 'Write a message first' : isUploading ? 'Uploading image' : null

    const submit = (): void => {
        // Guards the Cmd+Enter path, which skips the button's own disabled state.
        if (sending || blockedReason || !editorRef.current) {
            return
        }
        onSend(serializeToMarkdown(editorRef.current.getJSON()), () => {
            editorRef.current?.clear()
            setIsEmpty(true)
        })
    }

    return (
        <div className="flex flex-col gap-2">
            <SupportEditor
                initialContent={typeof draftContent === 'string' ? null : draftContent}
                placeholder={placeholder}
                autoFocus={autoFocus}
                onCreate={(editor) => {
                    editorRef.current = editor
                    if (draftContent) {
                        editor.setContent(draftContent)
                        setIsEmpty(false)
                    }
                }}
                onUpdate={setIsEmpty}
                onPressCmdEnter={submit}
                onUploadingChange={setIsUploading}
                disabled={sending}
                minRows={minRows}
            />
            <div className="flex items-center justify-end gap-2">
                <KbdGroup className="text-muted-foreground">
                    <Kbd>⌘</Kbd>
                    <Kbd>Enter</Kbd>
                </KbdGroup>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="primary"
                                loading={sending}
                                disabled={!!blockedReason}
                                onClick={submit}
                                data-attr="support-ticket-send"
                            />
                        }
                    >
                        {buttonText}
                    </TooltipTrigger>
                    {blockedReason && <TooltipContent>{blockedReason}</TooltipContent>}
                </Tooltip>
            </div>
        </div>
    )
}
