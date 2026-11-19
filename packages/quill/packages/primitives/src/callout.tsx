import './callout.css'

import { CircleCheckIcon, InfoIcon, OctagonAlertIcon, TriangleAlertIcon, XIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Item, ItemActions, ItemContent, ItemMedia } from './item'
import { cn } from './lib/utils'

/*
 * Callout is a static, inline message that stays in the layout: a warning above
 * a form, an info note in a panel, an error after a failed load. It is the quill
 * replacement for `LemonBanner`. Under the hood it is an outline `Item` with a
 * semantic `tone`, so it shares Item's tint, border and spacing.
 *
 *   <Callout tone="warning">
 *     <CalloutIcon />
 *     <CalloutContent>
 *       <CalloutTitle>Title</CalloutTitle>
 *       <CalloutDescription>Body text, links, or a list</CalloutDescription>
 *     </CalloutContent>
 *     <CalloutActions>
 *       <Button variant="outline">Action</Button>
 *     </CalloutActions>
 *     <CalloutClose onClick={dismiss} />
 *   </Callout>
 *
 * Callout sets no live-region role. Pass `role="alert"` (urgent) or
 * `role="status"` (polite) only when it appears after a user action and
 * screen readers must announce it.
 */

type CalloutTone = 'default' | 'info' | 'success' | 'warning' | 'destructive'

const CalloutToneContext = React.createContext<CalloutTone>('default')

const defaultToneLabels: Record<CalloutTone, string | null> = {
    default: null,
    info: 'Info: ',
    success: 'Success: ',
    warning: 'Warning: ',
    destructive: 'Error: ',
}

// No `size`: the narrow layout and the icon and close offsets in callout.css assume Item's `sm` spacing.
type CalloutProps = Omit<React.ComponentProps<typeof Item>, 'variant' | 'tone' | 'size'> & {
    tone?: CalloutTone
    /**
     * Screen reader prefix that names the tone, because the tint and icon are visual only.
     * Rendered as given, so include the separator. Defaults per tone ("Warning: ", "Error: ").
     * Pass `null` when the text already names the tone.
     */
    toneLabel?: React.ReactNode
}

const Callout = React.forwardRef<HTMLDivElement, CalloutProps>(function Callout(
    { className, tone = 'default', toneLabel = defaultToneLabels[tone], children, ...props },
    ref
) {
    return (
        <CalloutToneContext.Provider value={tone}>
            <Item
                ref={ref}
                variant="outline"
                tone={tone}
                size="sm"
                // The icon and the close button pin to the first line of text, so `items-start`, and callout.css offsets them.
                // With actions, the text gets a 16rem basis so the actions wrap under it before they squeeze it.
                // Both are utilities, not callout.css, because Item's `items-center` and `flex-1` utilities beat the components layer.
                className={cn(
                    'quill-callout items-start',
                    '[&:has(>[data-slot=callout-actions])>[data-slot=callout-content]]:flex-[1_1_16rem]',
                    className
                )}
                {...props}
            >
                {toneLabel != null && (
                    <span data-slot="callout-tone-label" className="sr-only">
                        {toneLabel}
                    </span>
                )}
                {children}
            </Item>
        </CalloutToneContext.Provider>
    )
})

const defaultToneIcons: Record<CalloutTone, React.ComponentType> = {
    default: InfoIcon,
    info: InfoIcon,
    success: CircleCheckIcon,
    warning: TriangleAlertIcon,
    destructive: OctagonAlertIcon,
}

/** Leading icon. Renders the tone's default icon when it has no children. */
const CalloutIcon = React.forwardRef<HTMLDivElement, Omit<React.ComponentProps<typeof ItemMedia>, 'variant'>>(
    function CalloutIcon({ className, children, ...props }, ref) {
        const DefaultIcon = defaultToneIcons[React.useContext(CalloutToneContext)]
        return (
            <ItemMedia
                ref={ref}
                variant="icon"
                aria-hidden
                className={cn('quill-callout__icon', className)}
                {...props}
                data-slot="callout-icon"
            >
                {children ?? <DefaultIcon />}
            </ItemMedia>
        )
    }
)

/** Holds the title and description. Takes the free width and lets long text wrap. */
const CalloutContent = React.forwardRef<HTMLDivElement, Omit<React.ComponentProps<typeof ItemContent>, 'variant'>>(
    function CalloutContent({ className, ...props }, ref) {
        return (
            <ItemContent
                ref={ref}
                className={cn('quill-callout__content', className)}
                {...props}
                data-slot="callout-content"
            />
        )
    }
)

/** Optional bold first line. */
const CalloutTitle = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function CalloutTitle(
    { className, ...props },
    ref
) {
    return <div ref={ref} data-slot="callout-title" className={cn('quill-callout__title', className)} {...props} />
})

/**
 * The message. A `div`, not a `p`, so it can hold links, inline code or a list.
 * It does not clamp: a callout is prose and wraps onto as many lines as it needs.
 */
const CalloutDescription = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function CalloutDescription(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="callout-description"
            className={cn('quill-callout__description', className)}
            {...props}
        />
    )
})

/** Buttons for the callout, usually one `Button variant="outline"`. In a narrow callout they move below the text. */
const CalloutActions = React.forwardRef<HTMLDivElement, React.ComponentProps<typeof ItemActions>>(
    function CalloutActions({ className, ...props }, ref) {
        return (
            <ItemActions
                ref={ref}
                className={cn('quill-callout__actions', className)}
                {...props}
                data-slot="callout-actions"
            />
        )
    }
)

/** Dismiss button. The caller owns the dismissed state. */
const CalloutClose = React.forwardRef<HTMLButtonElement, React.ComponentProps<typeof Button>>(function CalloutClose(
    { className, children, 'aria-label': ariaLabel = 'Dismiss', ...props },
    ref
) {
    return (
        <Button
            ref={ref}
            // 24px meets the WCAG 2.5.8 minimum target size without relying on the spacing exception.
            size="icon-sm"
            aria-label={ariaLabel}
            className={cn('quill-callout__close', className)}
            {...props}
            // After the spread because a wrapper such as TooltipTrigger passes its own data-slot through `render`.
            data-slot="callout-close"
        >
            {children ?? <XIcon />}
        </Button>
    )
})

export {
    Callout,
    CalloutIcon,
    CalloutContent,
    CalloutTitle,
    CalloutDescription,
    CalloutActions,
    CalloutClose,
    type CalloutTone,
    type CalloutProps,
}
