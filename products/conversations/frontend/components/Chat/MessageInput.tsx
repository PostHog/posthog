import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

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
    const [messageContent, setMessageContent] = useState('')
    const clearInputRef = useRef<(() => void) | null>(null)

    // Set up the clear callback that parent can call on success
    useEffect(() => {
        clearInputRef.current = () => setMessageContent('')
    })

    const handleSubmit = (): void => {
        if (messageContent.trim()) {
            // Pass callback that parent calls on success
            onSendMessage(messageContent, () => {
                setMessageContent('')
            })
        }
    }

    return (
        <div>
            <LemonTextArea
                placeholder={placeholder}
                value={messageContent}
                onChange={setMessageContent}
                minRows={minRows}
                disabled={messageSending}
            />
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    onClick={handleSubmit}
                    loading={messageSending}
                    disabled={!messageContent.trim()}
                    className="mt-2"
                >
                    {buttonText}
                </LemonButton>
            </div>
        </div>
    )
}
