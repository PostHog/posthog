import * as React from 'react'

import {
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
    Drawer,
    DrawerClose,
    DrawerContent,
    DrawerDescription,
    DrawerFooter,
    DrawerHeader,
    DrawerTitle,
    DrawerTrigger,
    ScrollArea,
    cn,
} from '@posthog/quill-primitives'

import { useMediaQuery } from './use-media-query'

/** Tailwind's `md` breakpoint: the same 768px where the app shell changes to its phone layout. */
const DIALOG_QUERY = '(min-width: 48rem)'

type CredenzaMode = 'dialog' | 'drawer'

interface CredenzaContextValue {
    mode: CredenzaMode
    /** Comes from the root, because a change of mode remounts every part. */
    triggerId: string
}

const CredenzaContext = React.createContext<CredenzaContextValue | null>(null)

function useCredenzaContext(part: string): CredenzaContextValue {
    const context = React.useContext(CredenzaContext)
    if (context === null) {
        throw new Error(`<${part}> must be inside <Credenza>`)
    }
    return context
}

interface CredenzaProps {
    open?: boolean
    defaultOpen?: boolean
    onOpenChange?: (open: boolean) => void
    children?: React.ReactNode
}

interface OpenChangeDetails {
    trigger: Element | undefined
}

/**
 * A change of mode remounts the popup and loses what the user typed, and a rotated phone crosses the breakpoint.
 * So the mode stays fixed from open until the close animation ends, then focus moves to the remounted trigger.
 */
function useStableMode(isOpen: boolean): {
    mode: CredenzaMode
    rememberTrigger: (open: boolean, details: OpenChangeDetails) => void
    handleOpenChangeComplete: (open: boolean) => void
} {
    const viewportMode: CredenzaMode = useMediaQuery(DIALOG_QUERY) ? 'dialog' : 'drawer'
    const [popupMode, setPopupMode] = React.useState<CredenzaMode | null>(null)
    if (isOpen && popupMode === null) {
        setPopupMode(viewportMode)
    }

    const openedByTriggerId = React.useRef<string | null>(null)
    const rememberTrigger = React.useCallback((open: boolean, details: OpenChangeDetails) => {
        if (open) {
            openedByTriggerId.current = details.trigger?.id || null
        }
    }, [])
    const handleOpenChangeComplete = React.useCallback((open: boolean) => {
        if (!open) {
            setPopupMode(null)
        }
    }, [])
    React.useLayoutEffect(() => {
        const triggerId = openedByTriggerId.current
        if (popupMode !== null || triggerId === null) {
            return
        }
        openedByTriggerId.current = null
        if (document.activeElement === document.body) {
            document.getElementById(triggerId)?.focus()
        }
    }, [popupMode])

    return { mode: popupMode ?? viewportMode, rememberTrigger, handleOpenChangeComplete }
}

/** A dialog on a wide viewport and a bottom drawer on a phone, with one set of parts for both. */
function Credenza({ open, defaultOpen = false, onOpenChange, children }: CredenzaProps): React.ReactElement {
    const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen)
    const isOpen = open ?? uncontrolledOpen
    const { mode, rememberTrigger, handleOpenChangeComplete } = useStableMode(isOpen)
    const triggerId = React.useId()
    const context = React.useMemo(() => ({ mode, triggerId }), [mode, triggerId])
    const handleOpenChange = React.useCallback(
        (next: boolean, details: OpenChangeDetails) => {
            rememberTrigger(next, details)
            setUncontrolledOpen(next)
            onOpenChange?.(next)
        },
        [rememberTrigger, onOpenChange]
    )

    return (
        <CredenzaContext.Provider value={context}>
            {mode === 'dialog' ? (
                <Dialog open={isOpen} onOpenChange={handleOpenChange} onOpenChangeComplete={handleOpenChangeComplete}>
                    {children}
                </Dialog>
            ) : (
                <Drawer
                    open={isOpen}
                    onOpenChange={handleOpenChange}
                    onOpenChangeComplete={handleOpenChangeComplete}
                    swipeDirection="down"
                >
                    {children}
                </Drawer>
            )}
        </CredenzaContext.Provider>
    )
}

interface CredenzaButtonProps extends React.ComponentPropsWithoutRef<'button'> {
    render?: React.ReactElement
    /** Set to `false` when `render` is not a native `<button>`. */
    nativeButton?: boolean
}

/** Not `React.ComponentType`: its `propTypes` check fails on Base UI's function `className`. */
type ModePart<Props, Ref> = (props: React.PropsWithoutRef<Props> & React.RefAttributes<Ref>) => React.ReactNode

function credenzaPart<Props extends object, Ref extends HTMLElement>(
    name: string,
    DialogPart: ModePart<Props, Ref>,
    DrawerPart: ModePart<Props, Ref>
): React.ForwardRefExoticComponent<React.PropsWithoutRef<Props> & React.RefAttributes<Ref>> {
    const Part = React.forwardRef<Ref, Props>(function CredenzaPart(props, ref) {
        const Rendered = useCredenzaContext(name).mode === 'dialog' ? DialogPart : DrawerPart
        return <Rendered ref={ref} {...props} />
    })
    Part.displayName = name
    return Part
}

const DrawerBody = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<'div'>>(function DrawerBody(
    { className, ...props },
    ref
) {
    return (
        <ScrollArea
            ref={ref}
            data-slot="credenza-body"
            // The drawer has no fixed height, so the viewport fills the space the flex layout leaves it.
            className={cn('flex min-h-0 flex-1 flex-col', className)}
            viewportClassName="min-h-0 flex-1 px-4"
            {...props}
        />
    )
})

const DrawerStackedFooter = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<'div'>>(
    function DrawerStackedFooter({ className, ...props }, ref) {
        return <DrawerFooter ref={ref} className={cn('flex-col-reverse', className)} {...props} />
    }
)

/** A credenza with more than one trigger needs an `id` on each, because they cannot share the default id. */
const CredenzaTrigger = React.forwardRef<HTMLButtonElement, CredenzaButtonProps>(function CredenzaTrigger(
    { id, ...props },
    ref
) {
    const { mode, triggerId } = useCredenzaContext('CredenzaTrigger')
    return mode === 'dialog' ? (
        <DialogTrigger ref={ref} id={id ?? triggerId} {...props} />
    ) : (
        <DrawerTrigger ref={ref} id={id ?? triggerId} {...props} />
    )
})

const CredenzaContent = credenzaPart<React.ComponentPropsWithoutRef<'div'>, HTMLDivElement>(
    'CredenzaContent',
    DialogContent,
    DrawerContent
)

const CredenzaHeader = credenzaPart<React.ComponentPropsWithoutRef<'div'>, HTMLDivElement>(
    'CredenzaHeader',
    DialogHeader,
    DrawerHeader
)

const CredenzaTitle = credenzaPart<React.ComponentPropsWithoutRef<'h2'>, HTMLHeadingElement>(
    'CredenzaTitle',
    DialogTitle,
    DrawerTitle
)

const CredenzaDescription = credenzaPart<React.ComponentPropsWithoutRef<'p'>, HTMLParagraphElement>(
    'CredenzaDescription',
    DialogDescription,
    DrawerDescription
)

const CredenzaBody = credenzaPart<React.ComponentPropsWithoutRef<'div'>, HTMLDivElement>(
    'CredenzaBody',
    DialogBody,
    DrawerBody
)

const CredenzaFooter = credenzaPart<React.ComponentPropsWithoutRef<'div'>, HTMLDivElement>(
    'CredenzaFooter',
    DialogFooter,
    DrawerStackedFooter
)

const CredenzaClose = credenzaPart<CredenzaButtonProps, HTMLButtonElement>('CredenzaClose', DialogClose, DrawerClose)

export {
    Credenza,
    CredenzaBody,
    CredenzaClose,
    CredenzaContent,
    CredenzaDescription,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    CredenzaTrigger,
    type CredenzaProps,
}
