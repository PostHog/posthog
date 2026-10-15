import { CircleCheckIcon, InfoIcon, OctagonAlertIcon, TriangleAlertIcon, XIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import './callout.css'
import { Item, ItemMedia } from './item'
import { cn } from './lib/utils'

/*
 * Callout is a static, inline message on the page: a warning above a form, an
 * info note in a settings panel, an error after a failed load. It is an Item
 * (outline variant + semantic tone), so the body composes from Item slots:
 *
 *   <Callout tone="warning">
 *     <CalloutIcon />
 *     <ItemContent>
 *       <ItemTitle>Title</ItemTitle>
 *       <ItemDescription>Body text</ItemDescription>
 *     </ItemContent>
 *     <ItemActions>
 *       <Button variant="outline">Action</Button>
 *     </ItemActions>
 *     <CalloutClose onClick={dismiss} />
 *   </Callout>
 *
 * Callout sets no live-region role. Pass `role="alert"` (urgent) or
 * `role="status"` (polite) only when the callout appears in response to a
 * user action and screen readers must announce it.
 */

type CalloutTone = 'default' | 'info' | 'success' | 'warning' | 'destructive'

const CalloutToneContext = React.createContext<CalloutTone>('default')

type CalloutProps = Omit<React.ComponentProps<typeof Item>, 'variant' | 'tone'> & {
    tone?: CalloutTone
}

const Callout = React.forwardRef<HTMLDivElement, CalloutProps>(function Callout(
    { className, tone = 'default', size = 'sm', ...props },
    ref
) {
    return (
        <CalloutToneContext.Provider value={tone}>
            <Item
                ref={ref}
                data-slot="callout"
                variant="outline"
                tone={tone}
                size={size}
                className={cn('quill-callout has-data-[slot=item-description]:items-start', className)}
                {...props}
            />
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
        const tone = React.useContext(CalloutToneContext)
        const DefaultIcon = defaultToneIcons[tone]
        return (
            <ItemMedia
                ref={ref}
                data-slot="callout-icon"
                variant="icon"
                aria-hidden
                className={cn('quill-callout__icon', className)}
                {...props}
            >
                {children ?? <DefaultIcon />}
            </ItemMedia>
        )
    }
)

/** Dismiss button. Put it last so it sits on the far right. The caller owns the dismissed state. */
const CalloutClose = React.forwardRef<HTMLButtonElement, React.ComponentProps<typeof Button>>(function CalloutClose(
    { className, children, 'aria-label': ariaLabel = 'Dismiss', ...props },
    ref
) {
    return (
        <Button
            ref={ref}
            data-slot="callout-close"
            size="icon-xs"
            aria-label={ariaLabel}
            className={cn('quill-callout__close', className)}
            {...props}
        >
            {children ?? <XIcon />}
        </Button>
    )
})

export { Callout, CalloutIcon, CalloutClose, type CalloutTone, type CalloutProps }
