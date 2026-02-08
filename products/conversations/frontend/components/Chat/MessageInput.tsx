import { JSONContent } from '@tiptap/core'
import { useRef, useState } from 'react'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import { SupportEditor, serializeToMarkdown } from '../Editor'

export interface MessageInputProps {
    onSendMessage: (content: string, richContent: JSONContent | null, isPrivate: boolean, onSuccess: () => void) => void
    messageSending: boolean
    placeholder?: string
    buttonText?: string
    minRows?: number
    /** Whether to show the "Send as private" checkbox */
    showPrivateOption?: boolean
}

export function MessageInput({
    onSendMessage,
    messageSending,
    placeholder = 'Type your message...',
    buttonText = 'Send',
    minRows = 3,
    showPrivateOption = false,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(true)
    const [isUploading, setIsUploading] = useState(false)
    const [isPrivate, setIsPrivate] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)

    const handleSubmit = (): void => {
        if (editorRef.current && !isEmpty) {
            const richContent = editorRef.current.getJSON()
            const content = serializeToMarkdown(richContent)
            onSendMessage(content, richContent, isPrivate, () => {
                editorRef.current?.clear()
                setIsEmpty(true)
            })
        }
    }

    return (
        <div>
            <SupportEditor
                placeholder={placeholder}
                onCreate={(editor) => {
                    editorRef.current = editor
                }}
                onUpdate={(empty) => setIsEmpty(empty)}
                onPressCmdEnter={handleSubmit}
                onUploadingChange={setIsUploading}
                disabled={messageSending}
                minRows={minRows}
                className={isPrivate ? 'bg-warning-highlight border-warning' : undefined}
            />
            <div className="flex justify-between items-center mt-2">
                {showPrivateOption ? (
                    <Tooltip title="Private messages are only visible to your team, not to the customer">
                        <span>
                            <LemonCheckbox
                                checked={isPrivate}
                                onChange={setIsPrivate}
                                label={
                                    <span className="inline-flex items-center gap-1">
                                        <IconLock className="text-sm" />
                                        Send as private
                                    </span>
                                }
                            />
                        </span>
                    </Tooltip>
                ) : (
                    <div />
                )}
                <LemonButton
                    type="primary"
                    onClick={handleSubmit}
                    loading={messageSending}
                    disabledReason={isEmpty ? 'No message' : isUploading ? 'Uploading image...' : undefined}
                >
                    {buttonText}
                </LemonButton>
            </div>
        </div>
    )
}
