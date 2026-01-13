import { useState } from 'react'

import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

export interface MessageInputProps {
    onSendMessage: (content: string) => void
    messageSending: boolean
    placeholder?: string
    buttonText?: string
    multiline?: boolean
    minRows?: number
}

export function MessageInput({
    onSendMessage,
    messageSending,
    placeholder = 'Type your message...',
    buttonText = 'Send',
    multiline = false,
    minRows = 4,
}: MessageInputProps): JSX.Element {
    const [messageContent, setMessageContent] = useState('')

    const handleSubmit = (): void => {
        if (messageContent.trim()) {
            onSendMessage(messageContent)
            setMessageContent('')
        }
    }

    if (multiline) {
        return (
            <div className="flex flex-col gap-2">
                <LemonTextArea
                    placeholder={placeholder}
                    value={messageContent}
                    onChange={setMessageContent}
                    minRows={minRows}
                    disabled={messageSending}
                />
                <LemonButton
                    type="primary"
                    fullWidth
                    center
                    onClick={handleSubmit}
                    loading={messageSending}
                    disabled={!messageContent.trim()}
                >
                    {buttonText}
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex gap-2">
            <LemonInput
                className="flex-1"
                placeholder={placeholder}
                value={messageContent}
                onChange={setMessageContent}
                onPressEnter={handleSubmit}
                disabled={messageSending}
            />
            <LemonButton
                type="primary"
                onClick={handleSubmit}
                loading={messageSending}
                disabled={!messageContent.trim()}
            >
                {buttonText}
            </LemonButton>
        </div>
    )
}
