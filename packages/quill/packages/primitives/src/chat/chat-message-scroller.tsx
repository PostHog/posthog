import {
    MessageScroller as MessageScrollerPrimitive,
    useMessageScroller,
    useMessageScrollerScrollable,
    useMessageScrollerVisibility,
} from '@shadcn/react/message-scroller'
import { ArrowDownIcon } from 'lucide-react'
import * as React from 'react'

import './chat-message-scroller.css'
import { Button } from '../button'
import { cn } from '../lib/utils'

/**
 * Thin quill wrapper over the headless `@shadcn/react/message-scroller` engine.
 *
 * Non-virtualized by design: rows stay in the DOM, kept cheap via `content-visibility: auto` +
 * `contain-intrinsic-size` (see {@link ChatMessageScrollerItem}). Stick-to-bottom, anchoring, and
 * preserve-on-prepend are imperative inside the engine and surfaced through `data-*` attributes —
 * no React state on scroll. Styling lives in `chat-message-scroller.css` (quill convention).
 */
function ChatMessageScrollerProvider(
    props: React.ComponentProps<typeof MessageScrollerPrimitive.Provider>
): React.ReactElement {
    return <MessageScrollerPrimitive.Provider {...props} />
}

const ChatMessageScroller = React.forwardRef<
    React.ComponentRef<typeof MessageScrollerPrimitive.Root>,
    React.ComponentProps<typeof MessageScrollerPrimitive.Root>
>(function ChatMessageScroller({ className, ...props }, ref) {
    return (
        <MessageScrollerPrimitive.Root
            ref={ref}
            data-quill
            data-slot="chat-message-scroller"
            className={cn('quill-chat-message-scroller group/chat-message-scroller', className)}
            {...props}
        />
    )
})

const ChatMessageScrollerViewport = React.forwardRef<
    React.ComponentRef<typeof MessageScrollerPrimitive.Viewport>,
    React.ComponentProps<typeof MessageScrollerPrimitive.Viewport>
>(function ChatMessageScrollerViewport({ className, ...props }, ref) {
    return (
        <MessageScrollerPrimitive.Viewport
            ref={ref}
            data-slot="chat-message-scroller-viewport"
            className={cn('quill-chat-message-scroller__viewport', className)}
            {...props}
        />
    )
})

type ChatMessageScrollerContentProps = React.ComponentProps<typeof MessageScrollerPrimitive.Content> & {
    /** Row spacing: `dense` 0.5rem, `default` 1rem, `loose` 1.5rem. */
    density?: 'dense' | 'default' | 'loose'
}

const ChatMessageScrollerContent = React.forwardRef<
    React.ComponentRef<typeof MessageScrollerPrimitive.Content>,
    ChatMessageScrollerContentProps
>(function ChatMessageScrollerContent({ className, density = 'default', ...props }, ref) {
    return (
        <MessageScrollerPrimitive.Content
            ref={ref}
            data-slot="chat-message-scroller-content"
            data-density={density}
            className={cn('quill-chat-message-scroller__content', className)}
            {...props}
        />
    )
})

/**
 * One transcript row. `scrollAnchor` marks turn boundaries (the engine pins anchored rows near the
 * viewport top on new turns). Off-screen size estimate is tuned in `chat-message-scroller.css`.
 */
const ChatMessageScrollerItem = React.forwardRef<
    React.ComponentRef<typeof MessageScrollerPrimitive.Item>,
    React.ComponentProps<typeof MessageScrollerPrimitive.Item>
>(function ChatMessageScrollerItem({ className, scrollAnchor = false, ...props }, ref) {
    return (
        <MessageScrollerPrimitive.Item
            ref={ref}
            data-slot="chat-message-scroller-item"
            scrollAnchor={scrollAnchor}
            className={cn('quill-chat-message-scroller__item', className)}
            {...props}
        />
    )
})

/**
 * Scroll-to-edge control. The engine toggles `data-active` from imperative scroll tracking;
 * visibility/animation is pure CSS off that attribute.
 */
const ChatMessageScrollerButton = React.forwardRef<
    React.ComponentRef<typeof MessageScrollerPrimitive.Button>,
    React.ComponentProps<typeof MessageScrollerPrimitive.Button>
>(function ChatMessageScrollerButton({ direction = 'end', className, children, render, ...props }, ref) {
    return (
        <MessageScrollerPrimitive.Button
            ref={ref}
            data-slot="chat-message-scroller-button"
            data-direction={direction}
            direction={direction}
            className={cn('quill-chat-message-scroller__button', className)}
            render={render ?? <Button variant="outline" size="icon" />}
            {...props}
        >
            {children ?? (
                <>
                    <ArrowDownIcon className="size-4" />
                    <span className="sr-only">{direction === 'end' ? 'Scroll to end' : 'Scroll to start'}</span>
                </>
            )}
        </MessageScrollerPrimitive.Button>
    )
})

export {
    ChatMessageScrollerProvider,
    ChatMessageScroller,
    ChatMessageScrollerViewport,
    ChatMessageScrollerContent,
    ChatMessageScrollerItem,
    ChatMessageScrollerButton,
    useMessageScroller as useChatMessageScroller,
    useMessageScrollerScrollable as useChatMessageScrollerScrollable,
    useMessageScrollerVisibility as useChatMessageScrollerVisibility,
}
