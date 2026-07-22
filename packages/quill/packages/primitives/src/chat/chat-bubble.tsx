import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './chat-bubble.css'
import { cn } from '../lib/utils'

/**
 * Bubble surface primitives, vendored from the shadcn `base-mira` registry and renamed `ChatX`.
 * Scoped to the bubble surface only — avatar/name/timestamps/actions live on {@link ./chat-message}.
 *
 * Styling lives in `chat-bubble.css` (quill convention). Variants are intentionally generic;
 * restyle per product. Assistant turns use `variant="ghost"` (transparent, full-width); user turns
 * use a filled variant.
 */
function ChatBubbleGroup({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-quill data-slot="bubble-group" className={cn('quill-chat-bubble-group', className)} {...props} />
}

const bubbleVariants = cva('quill-chat-bubble', {
    variants: {
        variant: {
            default: 'quill-chat-bubble--variant-default',
            secondary: 'quill-chat-bubble--variant-secondary',
            muted: 'quill-chat-bubble--variant-muted',
            tinted: 'quill-chat-bubble--variant-tinted',
            outline: 'quill-chat-bubble--variant-outline',
            ghost: 'quill-chat-bubble--variant-ghost',
            destructive: 'quill-chat-bubble--variant-destructive',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

function ChatBubble({
    variant = 'default',
    align = 'start',
    className,
    ...props
}: React.ComponentProps<'div'> & VariantProps<typeof bubbleVariants> & { align?: 'start' | 'end' }): React.ReactElement {
    return (
        <div
            data-quill
            data-slot="bubble"
            data-variant={variant}
            data-align={align}
            className={cn(bubbleVariants({ variant }), className)}
            {...props}
        />
    )
}

function ChatBubbleContent({ className, render, ...props }: useRender.ComponentProps<'div'>): React.ReactElement {
    return useRender({
        defaultTagName: 'div',
        props: mergeProps<'div'>(
            {
                'data-slot': 'bubble-content',
                className: cn('quill-chat-bubble__content', className),
            } as Omit<React.ComponentProps<'div'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'bubble-content',
        },
    })
}

function ChatBubbleReactions({
    side = 'bottom',
    align = 'end',
    className,
    ...props
}: React.ComponentProps<'div'> & { align?: 'start' | 'end'; side?: 'top' | 'bottom' }): React.ReactElement {
    return (
        <div
            data-slot="bubble-reactions"
            data-align={align}
            data-side={side}
            className={cn('quill-chat-bubble-reactions', className)}
            {...props}
        />
    )
}

export { ChatBubbleGroup, ChatBubble, ChatBubbleContent, ChatBubbleReactions, bubbleVariants }
