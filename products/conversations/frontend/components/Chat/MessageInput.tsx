import { generateText } from '@tiptap/core'
import { useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import {
    DEFAULT_EXTENSIONS,
    LemonRichContentEditor,
    serializationOptions,
} from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'

export interface MessageInputProps {
    onSendMessage: (content: string, onSuccess: () => void) => void
    messageSending: boolean
    placeholder?: string
    buttonText?: string
    minRows?: number
}

export function MessageInput({
    onSendMessage,
    messageSending,
    placeholder = 'Type your message...',
    buttonText = 'Send',
    minRows = 3,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(true)
    const editorRef = useRef<RichContentEditorType | null>(null)

    const handleSubmit = (): void => {
        if (editorRef.current && !isEmpty) {
            const content = generateText(editorRef.current.getJSON(), DEFAULT_EXTENSIONS, serializationOptions)
            onSendMessage(content, () => {
                editorRef.current?.clear()
                setIsEmpty(true)
            })
        }
    }

    return (
        <div>
            <LemonRichContentEditor
                placeholder={placeholder}
                onCreate={(editor) => {
                    editorRef.current = editor
                }}
                onUpdate={(empty) => setIsEmpty(empty)}
                onPressCmdEnter={handleSubmit}
                disabled={messageSending}
                minRows={minRows}
            />
            <div className="flex justify-end mt-2">
                <LemonButton
                    type="primary"
                    onClick={handleSubmit}
                    loading={messageSending}
                    disabledReason={isEmpty ? 'No message' : undefined}
                >
                    {buttonText}
                </LemonButton>
            </div>
        </div>
    )
}
