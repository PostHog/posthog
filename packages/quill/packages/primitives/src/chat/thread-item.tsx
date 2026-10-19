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
const ThreadItemGroup = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ThreadItemGroup(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-quill
            data-slot="thread-item-group"
            className={cn('quill-thread-item-group', className)}
            {...props}
        />
    )
})

const ThreadItem = React.forwardRef<HTMLElement, React.ComponentProps<'article'>>(function ThreadItem(
    { className, ...props },
    ref
) {
    return (
        <article
            ref={ref}
            data-quill
            data-slot="thread-item"
            className={cn('quill-thread-item', className)}
            {...props}
        />
    )
})

const ThreadItemGutter = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ThreadItemGutter(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="thread-item-gutter"
            className={cn('quill-thread-item__gutter', className)}
            {...props}
        />
    )
})

const ThreadItemContent = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ThreadItemContent(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="thread-item-content"
            className={cn('quill-thread-item__content', className)}
            {...props}
        />
    )
})

const ThreadItemHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ThreadItemHeader(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="thread-item-header"
            className={cn('quill-thread-item__header', className)}
            {...props}
        />
    )
})

/** Author name. Renders a `span` by default; pass `render={<button />}` to make it a profile trigger. */
const ThreadItemAuthor = React.forwardRef<HTMLSpanElement, useRender.ComponentProps<'span'>>(function ThreadItemAuthor(
    { className, render, ...props },
    ref
) {
    return useRender({
        ref,
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
})

/** Semantic `<time>` — pass `dateTime` so assistive tech gets the machine-readable value. */
const ThreadItemTimestamp = React.forwardRef<HTMLTimeElement, React.ComponentProps<'time'>>(
    function ThreadItemTimestamp({ className, ...props }, ref) {
        return (
            <time
                ref={ref}
                data-slot="thread-item-timestamp"
                className={cn('quill-thread-item__timestamp', className)}
                {...props}
            />
        )
    }
)

const ThreadItemBody = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ThreadItemBody(
    { className, ...props },
    ref
) {
    return (
        <div ref={ref} data-slot="thread-item-body" className={cn('quill-thread-item__body', className)} {...props} />
    )
})

/**
 * Inline @mention pill inside {@link ThreadItemBody}. Renders a `span` by default; pass
 * `render={<button type="button" />}` (or `<a />`) when clicking it should open a profile.
 */
const ThreadItemMention = React.forwardRef<HTMLSpanElement, useRender.ComponentProps<'span'>>(
    function ThreadItemMention({ className, render, ...props }, ref) {
        return useRender({
            ref,
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
)

/** Inline link inside {@link ThreadItemBody} — primary color, underline on hover. */
const ThreadItemLink = React.forwardRef<HTMLAnchorElement, useRender.ComponentProps<'a'>>(function ThreadItemLink(
    { className, render, ...props },
    ref
) {
    return useRender({
        ref,
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
})

/**
 * Collapsible attachment (image/file preview) — a Base UI Collapsible, open by default. The
 * trigger carries the filename and a rotating chevron; keyboard/AT get `aria-expanded` for free.
 */
const ThreadItemAttachment = React.forwardRef<
    React.ComponentRef<typeof CollapsiblePrimitive.Root>,
    CollapsiblePrimitive.Root.Props
>(function ThreadItemAttachment({ className, defaultOpen = true, ...props }, ref) {
    return (
        <CollapsiblePrimitive.Root
            ref={ref}
            data-quill
            data-slot="thread-item-attachment"
            defaultOpen={defaultOpen}
            className={cn('quill-thread-item__attachment', className)}
            {...props}
        />
    )
})

/** Filename row that toggles the attachment preview. Children become the visible label. */
const ThreadItemAttachmentTrigger = React.forwardRef<
    React.ComponentRef<typeof CollapsiblePrimitive.Trigger>,
    CollapsiblePrimitive.Trigger.Props
>(function ThreadItemAttachmentTrigger({ children, className, ...props }, ref) {
    return (
        <CollapsiblePrimitive.Trigger
            ref={ref}
            data-slot="thread-item-attachment-trigger"
            className={cn('quill-thread-item__attachment-trigger', className)}
            {...props}
        >
            {children}
            <ChevronDownIcon data-chevron="down" className="pointer-events-none shrink-0" />
        </CollapsiblePrimitive.Trigger>
    )
})

const ThreadItemAttachmentContent = React.forwardRef<
    React.ComponentRef<typeof CollapsiblePrimitive.Panel>,
    CollapsiblePrimitive.Panel.Props
>(function ThreadItemAttachmentContent({ children, className, ...props }, ref) {
    return (
        <CollapsiblePrimitive.Panel
            ref={ref}
            data-slot="thread-item-attachment-content"
            className="quill-thread-item__attachment-panel"
            {...props}
        >
            <div className={cn('quill-thread-item__attachment-panel-content', className)}>{children}</div>
        </CollapsiblePrimitive.Panel>
    )
})

/** Framed image preview. `alt` is required — describe the image (empty `alt=""` only if purely decorative). */
const ThreadItemAttachmentImage = React.forwardRef<HTMLImageElement, React.ComponentProps<'img'> & { alt: string }>(
    function ThreadItemAttachmentImage({ className, alt, ...props }, ref) {
        return (
            <img
                ref={ref}
                alt={alt}
                data-slot="thread-item-attachment-image"
                className={cn('quill-thread-item__attachment-image', className)}
                {...props}
            />
        )
    }
)

const ThreadItemReactions = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ThreadItemReactions(
    { className, 'aria-label': ariaLabel = 'Reactions', ...props },
    ref
) {
    return (
        <div
            ref={ref}
            role="group"
            aria-label={ariaLabel}
            data-slot="thread-item-reactions"
            className={cn('quill-thread-item__reactions', className)}
            {...props}
        />
    )
})

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
const ThreadItemReactionEmoji = React.forwardRef<HTMLSpanElement, React.ComponentProps<'span'>>(
    function ThreadItemReactionEmoji({ className, ...props }, ref) {
        return (
            <span
                ref={ref}
                aria-hidden="true"
                data-slot="thread-item-reaction-emoji"
                className={cn('quill-thread-item__reaction-emoji', className)}
                {...props}
            />
        )
    }
)

const ThreadItemActionsContext = React.createContext(false)

/**
 * Hover-revealed actions toolbar, anchored to the item's top end corner. A Base UI Toolbar, so it
 * is one tab stop with arrow-key roving focus between actions. Hidden with opacity (not
 * `display: none`) so it stays keyboard-reachable — focus reveals it via `:focus-within`. Carries
 * its own `TooltipProvider`, so {@link ThreadItemAction} tooltips work without app-root setup and
 * moving between adjacent actions shares the provider's warm-up delay.
 */
const ThreadItemActions = React.forwardRef<
    React.ComponentRef<typeof ToolbarPrimitive.Root>,
    ToolbarPrimitive.Root.Props
>(function ThreadItemActions({ className, 'aria-label': ariaLabel = 'Message actions', ...props }, ref) {
    return (
        <ThreadItemActionsContext.Provider value={true}>
            <TooltipProvider>
                <ToolbarPrimitive.Root
                    ref={ref}
                    aria-label={ariaLabel}
                    data-slot="thread-item-actions"
                    className={cn('quill-thread-item__actions', className)}
                    {...props}
                />
            </TooltipProvider>
        </ThreadItemActionsContext.Provider>
    )
})

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
const ThreadItemReplies = React.forwardRef<React.ComponentRef<typeof Button>, ButtonProps>(function ThreadItemReplies(
    { className, ...props },
    ref
) {
    return (
        <Button
            ref={ref}
            data-slot="thread-item-replies"
            left
            className={cn('quill-thread-item__replies', className)}
            {...props}
        />
    )
})

const ThreadItemRepliesLabel = React.forwardRef<HTMLSpanElement, React.ComponentProps<'span'>>(
    function ThreadItemRepliesLabel({ className, ...props }, ref) {
        return (
            <span
                ref={ref}
                data-slot="thread-item-replies-label"
                className={cn('quill-thread-item__replies-label', className)}
                {...props}
            />
        )
    }
)

const ThreadItemRepliesMeta = React.forwardRef<HTMLSpanElement, React.ComponentProps<'span'>>(
    function ThreadItemRepliesMeta({ className, ...props }, ref) {
        return (
            <span
                ref={ref}
                data-slot="thread-item-replies-meta"
                className={cn('quill-thread-item__replies-meta', className)}
                {...props}
            />
        )
    }
)

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
