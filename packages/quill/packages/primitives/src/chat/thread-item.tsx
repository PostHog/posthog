import './thread-item.css'

import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { mergeProps } from '@base-ui/react/merge-props'
import { Toggle as TogglePrimitive } from '@base-ui/react/toggle'
import { Toolbar as ToolbarPrimitive } from '@base-ui/react/toolbar'
import { useRender } from '@base-ui/react/use-render'
import { ChevronDownIcon } from 'lucide-react'
import * as React from 'react'

import { Button, type ButtonProps } from '../button'
import { cn } from '../lib/utils'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../tooltip'

/**
 * Thread item primitives — a feed-style message row (avatar gutter, author + timestamp header,
 * body, reaction pills, reply summary, hover-revealed actions toolbar). Complements the bubble
 * primitives in {@link ./chat-bubble}: bubbles for conversational back-and-forth, thread items
 * for channel/feed surfaces where every message aligns start and actions appear on hover.
 *
 * Anatomy:
 *   ThreadItemGroup
 *     ThreadItem (article)
 *       ThreadItemGutter > Avatar (or ThreadItemTimestamp on continuation rows — shown on hover)
 *       ThreadItemContent
 *         ThreadItemHeader > ThreadItemAuthor + [Badge/meta] + ThreadItemTimestamp
 *         ThreadItemBody > text + ThreadItemMention + ThreadItemLink
 *         ThreadItemAttachment > ThreadItemAttachmentTrigger + ThreadItemAttachmentContent > ThreadItemAttachmentImage
 *         ThreadItemReactions > ThreadItemReaction > ThreadItemReactionEmoji + count
 *         ThreadItemReplies > AvatarGroup + ThreadItemRepliesLabel + ThreadItemRepliesMeta
 *       ThreadItemActions > ThreadItemAction(...)
 */
function ThreadItemGroup({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div data-quill data-slot="thread-item-group" className={cn('quill-thread-item-group', className)} {...props} />
    )
}

function ThreadItem({ className, ...props }: React.ComponentProps<'article'>): React.ReactElement {
    return <article data-quill data-slot="thread-item" className={cn('quill-thread-item', className)} {...props} />
}

function ThreadItemGutter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="thread-item-gutter" className={cn('quill-thread-item__gutter', className)} {...props} />
}

function ThreadItemContent({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="thread-item-content" className={cn('quill-thread-item__content', className)} {...props} />
}

function ThreadItemHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="thread-item-header" className={cn('quill-thread-item__header', className)} {...props} />
}

/** Author name. Renders a `span` by default; pass `render={<button />}` to make it a profile trigger. */
function ThreadItemAuthor({ className, render, ...props }: useRender.ComponentProps<'span'>): React.ReactElement {
    return useRender({
        defaultTagName: 'span',
        props: mergeProps<'span'>(
            {
                'data-slot': 'thread-item-author',
                className: cn('quill-thread-item__author', className),
            } as Omit<React.ComponentProps<'span'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'thread-item-author',
        },
    })
}

/** Semantic `<time>` — pass `dateTime` so assistive tech gets the machine-readable value. */
function ThreadItemTimestamp({ className, ...props }: React.ComponentProps<'time'>): React.ReactElement {
    return (
        <time data-slot="thread-item-timestamp" className={cn('quill-thread-item__timestamp', className)} {...props} />
    )
}

function ThreadItemBody({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="thread-item-body" className={cn('quill-thread-item__body', className)} {...props} />
}

/**
 * Inline @mention pill inside {@link ThreadItemBody}. Renders a `span` by default; pass
 * `render={<button type="button" />}` (or `<a />`) when clicking it should open a profile.
 */
function ThreadItemMention({ className, render, ...props }: useRender.ComponentProps<'span'>): React.ReactElement {
    return useRender({
        defaultTagName: 'span',
        props: mergeProps<'span'>(
            {
                'data-slot': 'thread-item-mention',
                className: cn('quill-thread-item__mention', className),
            } as Omit<React.ComponentProps<'span'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'thread-item-mention',
        },
    })
}

/** Inline link inside {@link ThreadItemBody} — primary color, underline on hover. */
function ThreadItemLink({ className, render, ...props }: useRender.ComponentProps<'a'>): React.ReactElement {
    return useRender({
        defaultTagName: 'a',
        props: mergeProps<'a'>(
            {
                'data-slot': 'thread-item-link',
                className: cn('quill-thread-item__link', className),
            } as Omit<React.ComponentProps<'a'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'thread-item-link',
        },
    })
}

/**
 * Collapsible attachment (image/file preview) — a Base UI Collapsible, open by default. The
 * trigger carries the filename and a rotating chevron; keyboard/AT get `aria-expanded` for free.
 */
function ThreadItemAttachment({
    className,
    defaultOpen = true,
    ...props
}: CollapsiblePrimitive.Root.Props): React.ReactElement {
    return (
        <CollapsiblePrimitive.Root
            data-quill
            data-slot="thread-item-attachment"
            defaultOpen={defaultOpen}
            className={cn('quill-thread-item__attachment', className)}
            {...props}
        />
    )
}

/** Filename row that toggles the attachment preview. Children become the visible label. */
function ThreadItemAttachmentTrigger({
    children,
    className,
    ...props
}: CollapsiblePrimitive.Trigger.Props): React.ReactElement {
    return (
        <CollapsiblePrimitive.Trigger
            data-slot="thread-item-attachment-trigger"
            className={cn('quill-thread-item__attachment-trigger', className)}
            {...props}
        >
            {children}
            <ChevronDownIcon data-chevron="down" className="pointer-events-none shrink-0" />
        </CollapsiblePrimitive.Trigger>
    )
}

function ThreadItemAttachmentContent({
    children,
    className,
    ...props
}: CollapsiblePrimitive.Panel.Props): React.ReactElement {
    return (
        <CollapsiblePrimitive.Panel
            data-slot="thread-item-attachment-content"
            className="quill-thread-item__attachment-panel"
            {...props}
        >
            <div className={cn('quill-thread-item__attachment-panel-content', className)}>{children}</div>
        </CollapsiblePrimitive.Panel>
    )
}

/** Framed image preview. `alt` is required — describe the image (empty `alt=""` only if purely decorative). */
function ThreadItemAttachmentImage({
    className,
    alt,
    ...props
}: React.ComponentProps<'img'> & { alt: string }): React.ReactElement {
    return (
        <img
            alt={alt}
            data-slot="thread-item-attachment-image"
            className={cn('quill-thread-item__attachment-image', className)}
            {...props}
        />
    )
}

function ThreadItemReactions({
    className,
    'aria-label': ariaLabel = 'Reactions',
    ...props
}: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            role="group"
            aria-label={ariaLabel}
            data-slot="thread-item-reactions"
            className={cn('quill-thread-item__reactions', className)}
            {...props}
        />
    )
}

/**
 * A reaction pill — a Base UI Toggle, so `pressed`/`onPressedChange` and `aria-pressed` come for
 * free. Give it an `aria-label` naming the emoji and count ("victory hand, 1 reaction"); wrap the
 * emoji glyph in {@link ThreadItemReactionEmoji} so it stays out of the accessible name.
 */
const ThreadItemReaction = React.forwardRef<HTMLButtonElement, TogglePrimitive.Props>(function ThreadItemReaction(
    { className, ...props },
    ref
) {
    return (
        <TogglePrimitive
            ref={ref}
            data-quill
            data-slot="thread-item-reaction"
            className={cn('quill-thread-item__reaction', className)}
            {...props}
        />
    )
})

/** Decorative emoji glyph inside a reaction — hidden from the accessible name. */
function ThreadItemReactionEmoji({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return (
        <span
            aria-hidden="true"
            data-slot="thread-item-reaction-emoji"
            className={cn('quill-thread-item__reaction-emoji', className)}
            {...props}
        />
    )
}

const ThreadItemActionsContext = React.createContext(false)

/**
 * Hover-revealed actions toolbar, anchored to the item's top end corner. A Base UI Toolbar, so it
 * is one tab stop with arrow-key roving focus between actions. Hidden with opacity (not
 * `display: none`) so it stays keyboard-reachable — focus reveals it via `:focus-within`. Carries
 * its own `TooltipProvider`, so {@link ThreadItemAction} tooltips work without app-root setup and
 * moving between adjacent actions shares the provider's warm-up delay.
 */
function ThreadItemActions({
    className,
    'aria-label': ariaLabel = 'Message actions',
    ...props
}: ToolbarPrimitive.Root.Props): React.ReactElement {
    return (
        <ThreadItemActionsContext.Provider value={true}>
            <TooltipProvider>
                <ToolbarPrimitive.Root
                    aria-label={ariaLabel}
                    data-slot="thread-item-actions"
                    className={cn('quill-thread-item__actions', className)}
                    {...props}
                />
            </TooltipProvider>
        </ThreadItemActionsContext.Provider>
    )
}

/**
 * One icon action: a Button wrapped in a Tooltip. `label` is both the accessible name
 * (`aria-label`) and the tooltip content — one source of truth, so the tooltip can never drift
 * from what screen readers announce. Forwards all Button props, including `render`
 * (`render={<a href="…" />}` for a link action), and its ref reaches the underlying button — so it
 * works as a `render` target itself (e.g. `DropdownMenuTrigger render={<ThreadItemAction …/>}`).
 * Inside {@link ThreadItemActions} it joins the toolbar's roving focus and the tooltip provider is
 * built in; anywhere else (e.g. a reactions row) it needs a `TooltipProvider` ancestor.
 */
const ThreadItemAction = React.forwardRef<
    HTMLButtonElement,
    ButtonProps & {
        label: string
        tooltipSide?: React.ComponentProps<typeof TooltipContent>['side']
    }
>(function ThreadItemAction({ label, tooltipSide = 'top', size = 'icon-sm', children, ...props }, ref) {
    const inToolbar = React.useContext(ThreadItemActionsContext)
    const button = <Button ref={ref} data-slot="thread-item-action" size={size} aria-label={label} {...props} />
    return (
        <Tooltip>
            <TooltipTrigger render={inToolbar ? <ToolbarPrimitive.Button render={button} /> : button}>
                {children}
            </TooltipTrigger>
            <TooltipContent side={tooltipSide}>{label}</TooltipContent>
        </Tooltip>
    )
})

/**
 * Reply summary row — a Button (variant `default`: transparent at rest, fill on hover), stretched
 * to the content column. Opens the thread on click; pass `render={<a />}` for a link.
 */
function ThreadItemReplies({ className, ...props }: ButtonProps): React.ReactElement {
    return (
        <Button
            data-slot="thread-item-replies"
            left
            className={cn('quill-thread-item__replies', className)}
            {...props}
        />
    )
}

function ThreadItemRepliesLabel({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return (
        <span
            data-slot="thread-item-replies-label"
            className={cn('quill-thread-item__replies-label', className)}
            {...props}
        />
    )
}

function ThreadItemRepliesMeta({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return (
        <span
            data-slot="thread-item-replies-meta"
            className={cn('quill-thread-item__replies-meta', className)}
            {...props}
        />
    )
}

export {
    ThreadItemGroup,
    ThreadItem,
    ThreadItemGutter,
    ThreadItemContent,
    ThreadItemHeader,
    ThreadItemAuthor,
    ThreadItemTimestamp,
    ThreadItemBody,
    ThreadItemMention,
    ThreadItemLink,
    ThreadItemAttachment,
    ThreadItemAttachmentTrigger,
    ThreadItemAttachmentContent,
    ThreadItemAttachmentImage,
    ThreadItemReactions,
    ThreadItemReaction,
    ThreadItemReactionEmoji,
    ThreadItemActions,
    ThreadItemAction,
    ThreadItemReplies,
    ThreadItemRepliesLabel,
    ThreadItemRepliesMeta,
}
