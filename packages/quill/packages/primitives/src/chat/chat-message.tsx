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
const ChatMessageGroup = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ChatMessageGroup(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-quill
            data-slot="message-group"
            className={cn('quill-chat-message-group', className)}
            {...props}
        />
    )
})

const ChatMessage = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'> & { align?: 'start' | 'end' }>(
    function ChatMessage({ className, align = 'start', ...props }, ref) {
        return (
            <div
                ref={ref}
                data-quill
                data-slot="message"
                data-align={align}
                className={cn('quill-chat-message', className)}
                {...props}
            />
        )
    }
)

const ChatMessageAvatar = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ChatMessageAvatar(
    { className, ...props },
    ref
) {
    return (
        <div ref={ref} data-slot="message-avatar" className={cn('quill-chat-message__avatar', className)} {...props} />
    )
})

const ChatMessageContent = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ChatMessageContent(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="message-content"
            className={cn('quill-chat-message__content', className)}
            {...props}
        />
    )
})

const ChatMessageHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ChatMessageHeader(
    { className, ...props },
    ref
) {
    return (
        <div ref={ref} data-slot="message-header" className={cn('quill-chat-message__header', className)} {...props} />
    )
})

const ChatMessageFooter = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ChatMessageFooter(
    { className, ...props },
    ref
) {
    return (
        <div ref={ref} data-slot="message-footer" className={cn('quill-chat-message__footer', className)} {...props} />
    )
})

export {
    ChatMessageGroup,
    ChatMessage,
    ChatMessageAvatar,
    ChatMessageContent,
    ChatMessageFooter,
    ChatMessageHeader,
}
