import * as React from 'react'

import './chat-message.css'
import { cn } from '../lib/utils'

/**
 * Message row primitives, vendored from the shadcn `base-mira` registry and renamed `ChatX`.
 * Styling lives in `chat-message.css` (quill convention); `data-slot`/`data-align` attributes drive
 * the selectors. Avatar is optional.
 *
 * Anatomy:  ChatMessage > [ChatMessageAvatar] + ChatMessageContent > [Header] + Bubble + [Footer]
 */
function ChatMessageGroup({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-quill data-slot="message-group" className={cn('quill-chat-message-group', className)} {...props} />
}

function ChatMessage({
    className,
    align = 'start',
    ...props
}: React.ComponentProps<'div'> & { align?: 'start' | 'end' }): React.ReactElement {
    return (
        <div
            data-quill
            data-slot="message"
            data-align={align}
            className={cn('quill-chat-message', className)}
            {...props}
        />
    )
}

function ChatMessageAvatar({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="message-avatar" className={cn('quill-chat-message__avatar', className)} {...props} />
}

function ChatMessageContent({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="message-content" className={cn('quill-chat-message__content', className)} {...props} />
}

function ChatMessageHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="message-header" className={cn('quill-chat-message__header', className)} {...props} />
}

function ChatMessageFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="message-footer" className={cn('quill-chat-message__footer', className)} {...props} />
}

export {
    ChatMessageGroup,
    ChatMessage,
    ChatMessageAvatar,
    ChatMessageContent,
    ChatMessageFooter,
    ChatMessageHeader,
}
