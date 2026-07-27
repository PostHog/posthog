import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import './chat-marker.css'
import './lib/disclosure.css'
import { cn } from '../lib/utils'

/**
 * Everything an agent did, at every fill level — vendored from the shadcn `base-mira` registry and
 * renamed `ChatX`. Styling lives in `chat-marker.css` (quill convention).
 *
 * The fill levels are one primitive, not three. Resist splitting them back apart:
 *
 * - A **note** is the flat row: icon + text, nothing to open.
 * - A **tool call** adds `status` — it shimmers while `running` and goes destructive on `error` —
 *   and usually a `ChatMarkerValue` for the argument it acted on.
 * - A **group** passes `body` and drops the icon: the row becomes the joined-up summary ("Read 2
 *   files · Edited 1 file") and the calls behind it are markers of their own inside. No single icon
 *   is honest about several tools at once, which is why the icon is a slot you fill, not a fixture.
 *
 * Quill divergence from stock shadcn Marker: pass `body` to make it collapsible. The row becomes a
 * Base-UI Collapsible trigger (hover reveals a chevron + `bg-fill-hover`, click toggles, the body
 * renders below). Collapse state is uncontrolled via `defaultOpen`; `open`/`onOpenChange` are there
 * for the rare case the app drives it (e.g. auto-expand the running tool).
 *
 * Fill the body with more markers, or with `ChatSourceList` when the tool returned pages.
 */
type ChatMarkerStatus = 'running' | 'done' | 'error'

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

const ChatMarkerContext = React.createContext<ChatMarkerStatus | undefined>(undefined)

type ChatMarkerProps = useRender.ComponentProps<'div'> &
    VariantProps<typeof markerVariants> & {
        /**
         * Omit for a settled note. `running` shimmers the content, `error` turns the row destructive,
         * `done` keeps the value it acted on. The app flips it; the primitive never infers it.
         */
        status?: ChatMarkerStatus
        /** Renders the marker as a collapsible: this becomes the expandable panel below the row. */
        body?: React.ReactNode
        /** Uncontrolled initial open state (only meaningful with `body`). */
        defaultOpen?: boolean
        open?: boolean
        onOpenChange?: (open: boolean) => void
    }

function ChatMarker({ body, ...props }: ChatMarkerProps): React.ReactElement {
    // Every value React renders as nothing means there's nothing to disclose. `body == null` alone
    // would miss `body={items.length > 0 && <List />}`, the usual way to pass one conditionally, and
    // give the row a chevron that opens onto an empty panel.
    const hasBody = body != null && body !== false && body !== ''
    return hasBody ? <ChatMarkerCollapsible body={body} {...props} /> : <ChatMarkerFlat {...props} />
}

function ChatMarkerFlat({
    className,
    variant = 'default',
    status,
    render,
    // `body`/collapse props are accepted by ChatMarker but inert in the flat path.
    defaultOpen: _defaultOpen,
    open: _open,
    onOpenChange: _onOpenChange,
    ...props
}: ChatMarkerProps): React.ReactElement {
    const row = useRender({
        defaultTagName: 'div',
        props: mergeProps<'div'>(
            {
                'data-quill': '',
                'data-slot': 'marker',
                'data-variant': variant,
                'data-status': status,
                className: cn('quill-chat-row', markerVariants({ variant, className })),
            } as Omit<React.ComponentProps<'div'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'marker',
            variant,
            status,
        },
    })

    return <ChatMarkerContext.Provider value={status}>{row}</ChatMarkerContext.Provider>
}

function ChatMarkerCollapsible({
    className,
    variant = 'default',
    status,
    body,
    defaultOpen,
    open,
    onOpenChange,
    children,
    render,
    ...props
}: ChatMarkerProps): React.ReactElement {
    return (
        <ChatMarkerContext.Provider value={status}>
            <CollapsiblePrimitive.Root
                data-quill
                data-slot="marker"
                data-variant={variant}
                data-status={status}
                defaultOpen={defaultOpen}
                open={open}
                onOpenChange={onOpenChange}
                className={cn(markerVariants({ variant }), 'quill-chat-marker--collapsible')}
            >
                <CollapsiblePrimitive.Trigger
                    className={cn(
                        'quill-chat-row',
                        'quill-chat-row--interactive',
                        'quill-chat-marker__trigger',
                        className
                    )}
                    render={render}
                    {...(props as React.ComponentProps<typeof CollapsiblePrimitive.Trigger>)}
                >
                    {children}
                    <ChevronRightIcon
                        aria-hidden="true"
                        className={cn('quill-chat-chevron', 'quill-chat-chevron--reveal')}
                    />
                </CollapsiblePrimitive.Trigger>
                <CollapsiblePrimitive.Panel
                    data-slot="marker-panel"
                    className={cn('quill-chat-collapse', 'quill-chat-rail', 'quill-chat-marker__panel')}
                >
                    {body}
                </CollapsiblePrimitive.Panel>
            </CollapsiblePrimitive.Root>
        </ChatMarkerContext.Provider>
    )
}

function ChatMarkerIcon({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return (
        <span
            data-slot="marker-icon"
            aria-hidden="true"
            className={cn('quill-chat-marker__icon', className)}
            {...props}
        />
    )
}

function ChatMarkerContent({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    const status = React.useContext(ChatMarkerContext)
    return (
        <span
            data-slot="marker-content"
            className={cn('quill-chat-marker__content', status === 'running' && 'quill-shimmer', className)}
            {...props}
        />
    )
}

/** The argument a call acted on — a query, a path, a command. Quoted, and kept once it settles. */
function ChatMarkerValue({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="marker-value" className={cn('quill-chat-marker__value', className)} {...props} />
}

export { ChatMarker, ChatMarkerIcon, ChatMarkerContent, ChatMarkerValue, markerVariants, type ChatMarkerStatus }
