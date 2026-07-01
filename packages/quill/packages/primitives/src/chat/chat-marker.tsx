import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import './chat-marker.css'
import { cn } from '../lib/utils'

/**
 * Inline status / system-note / separator row — vendored from the shadcn `base-mira` registry
 * and renamed `ChatX`. Styling lives in `chat-marker.css` (quill convention).
 *
 * Quill divergence from stock shadcn Marker: pass `body` to make it collapsible. With a body the
 * row becomes a Base-UI Collapsible trigger (hover reveals a chevron + `bg-fill-hover`, click
 * toggles, the body renders below). Without a body it's the flat shadcn marker. This is how a
 * single tool, a tool-group summary, and a status note are all the same primitive at different
 * fill levels. Collapse state is uncontrolled via `defaultOpen`; `open`/`onOpenChange` are there
 * for the rare case the app drives it (e.g. auto-expand the running tool).
 */
const markerVariants = cva('quill-chat-marker', {
    variants: {
        variant: {
            default: '',
            separator: 'quill-chat-marker--separator',
            border: 'quill-chat-marker--border',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

type ChatMarkerProps = useRender.ComponentProps<'div'> &
    VariantProps<typeof markerVariants> & {
        /** Renders the marker as a collapsible: this becomes the expandable panel below the row. */
        body?: React.ReactNode
        /** Uncontrolled initial open state (only meaningful with `body`). */
        defaultOpen?: boolean
        open?: boolean
        onOpenChange?: (open: boolean) => void
    }

function ChatMarker({ body, ...props }: ChatMarkerProps): React.ReactElement {
    return body == null ? <ChatMarkerFlat {...props} /> : <ChatMarkerCollapsible body={body} {...props} />
}

function ChatMarkerFlat({
    className,
    variant = 'default',
    render,
    // `body`/collapse props are accepted by ChatMarker but inert in the flat path.
    defaultOpen: _defaultOpen,
    open: _open,
    onOpenChange: _onOpenChange,
    ...props
}: ChatMarkerProps): React.ReactElement {
    return useRender({
        defaultTagName: 'div',
        props: mergeProps<'div'>(
            {
                'data-quill': '',
                'data-slot': 'marker',
                'data-variant': variant,
                className: cn(markerVariants({ variant, className })),
            } as Omit<React.ComponentProps<'div'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'marker',
            variant,
        },
    })
}

function ChatMarkerCollapsible({
    className,
    variant = 'default',
    body,
    defaultOpen,
    open,
    onOpenChange,
    children,
    render,
    ...props
}: ChatMarkerProps): React.ReactElement {
    return (
        <CollapsiblePrimitive.Root
            data-quill
            data-slot="marker"
            data-variant={variant}
            defaultOpen={defaultOpen}
            open={open}
            onOpenChange={onOpenChange}
            className={cn(markerVariants({ variant }), 'quill-chat-marker--collapsible')}
        >
            <CollapsiblePrimitive.Trigger
                className={cn('quill-chat-marker__trigger', className)}
                render={render}
                {...(props as React.ComponentProps<typeof CollapsiblePrimitive.Trigger>)}
            >
                {children}
                <ChevronRightIcon aria-hidden="true" className="quill-chat-marker__chevron" />
            </CollapsiblePrimitive.Trigger>
            <CollapsiblePrimitive.Panel data-slot="marker-panel" className="quill-chat-marker__panel">
                {body}
            </CollapsiblePrimitive.Panel>
        </CollapsiblePrimitive.Root>
    )
}

function ChatMarkerIcon({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="marker-icon" aria-hidden="true" className={cn('quill-chat-marker__icon', className)} {...props} />
}

function ChatMarkerContent({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="marker-content" className={cn('quill-chat-marker__content', className)} {...props} />
}

export { ChatMarker, ChatMarkerIcon, ChatMarkerContent, markerVariants }
