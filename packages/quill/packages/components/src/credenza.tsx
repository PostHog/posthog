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
    DrawerBody,
    DrawerClose,
    DrawerContent,
    DrawerDescription,
    DrawerFooter,
    DrawerHeader,
    DrawerTitle,
    createDrawerHandle,
} from '@posthog/quill-primitives'

import { useMediaQuery } from './use-media-query'

/** Tailwind's `md` breakpoint: the same 768px where the app shell changes to its phone layout. */
const DIALOG_QUERY = '(min-width: 48rem)'

type CredenzaMode = 'dialog' | 'drawer'

interface CredenzaProps {
    open?: boolean
    defaultOpen?: boolean
    onOpenChange?: (open: boolean) => void
    children?: React.ReactNode
}

interface CredenzaRootProps {
    handle: ReturnType<typeof createDrawerHandle>
    open: boolean
    onOpenChange: (open: boolean) => void
    onOpenChangeComplete: (open: boolean) => void
}

interface CredenzaContextValue {
    mode: CredenzaMode
    rootProps: CredenzaRootProps
}

const CredenzaContext = React.createContext<CredenzaContextValue | null>(null)

function useCredenzaContext(part: string): CredenzaContextValue {
    const context = React.useContext(CredenzaContext)
    if (context === null) {
        throw new Error(`<${part}> must be inside <Credenza>`)
    }
    return context
}

/**
 * A change of mode remounts the popup and loses what the user typed, and a rotated phone crosses the breakpoint.
 * So the mode stays fixed from open until the close animation ends.
 */
function useCredenzaState({
    open,
    defaultOpen = false,
    onOpenChange,
}: Omit<CredenzaProps, 'children'>): CredenzaContextValue {
    const [handle] = React.useState(createDrawerHandle)
    const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen)
    const isOpen = open ?? uncontrolledOpen

    const viewportMode: CredenzaMode = useMediaQuery(DIALOG_QUERY) ? 'dialog' : 'drawer'
    const [popupMode, setPopupMode] = React.useState<CredenzaMode | null>(null)
    if (isOpen && popupMode === null) {
        setPopupMode(viewportMode)
    }

    const handleOpenChange = React.useCallback(
        (next: boolean) => {
            setUncontrolledOpen(next)
            onOpenChange?.(next)
        },
        [onOpenChange]
    )
    const handleOpenChangeComplete = React.useCallback((next: boolean) => {
        if (!next) {
            setPopupMode(null)
        }
    }, [])

    return React.useMemo(
        () => ({
            mode: popupMode ?? viewportMode,
            rootProps: {
                handle,
                open: isOpen,
                onOpenChange: handleOpenChange,
                onOpenChangeComplete: handleOpenChangeComplete,
            },
        }),
        [popupMode, viewportMode, handle, isOpen, handleOpenChange, handleOpenChangeComplete]
    )
}

/** A dialog on a wide viewport and a bottom drawer on a phone, with one set of parts for both. */
function Credenza({ children, ...state }: CredenzaProps): React.ReactElement {
    return <CredenzaContext.Provider value={useCredenzaState(state)}>{children}</CredenzaContext.Provider>
}

/** Base UI's drawer trigger is its dialog trigger, so one trigger serves both modes. */
const CredenzaTrigger = React.forwardRef<
    HTMLButtonElement,
    Omit<React.ComponentPropsWithoutRef<typeof DialogTrigger>, 'handle'>
>(function CredenzaTrigger(props, ref) {
    const { handle } = useCredenzaContext('CredenzaTrigger').rootProps
    return <DialogTrigger ref={ref} handle={handle} data-slot="credenza-trigger" {...props} />
})

/** The root lives here rather than in `Credenza`, so a change of mode remounts the popup and not the triggers. */
const CredenzaContent = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<'div'>>(
    function CredenzaContent(props, ref) {
        const { mode, rootProps } = useCredenzaContext('CredenzaContent')
        return mode === 'dialog' ? (
            <Dialog {...rootProps}>
                <DialogContent ref={ref} {...props} />
            </Dialog>
        ) : (
            <Drawer {...rootProps} swipeDirection="down">
                <DrawerContent ref={ref} {...props} />
            </Drawer>
        )
    }
)

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

const CredenzaHeader = credenzaPart<React.ComponentPropsWithoutRef<'div'>, HTMLDivElement>(
    'CredenzaHeader',
    DialogHeader,
    DrawerHeader
)

const CredenzaTitle = credenzaPart<React.ComponentPropsWithoutRef<typeof DialogTitle>, HTMLHeadingElement>(
    'CredenzaTitle',
    DialogTitle,
    DrawerTitle
)

const CredenzaDescription = credenzaPart<
    React.ComponentPropsWithoutRef<typeof DialogDescription>,
    HTMLParagraphElement
>('CredenzaDescription', DialogDescription, DrawerDescription)

const CredenzaBody = credenzaPart<React.ComponentPropsWithoutRef<typeof DialogBody>, HTMLDivElement>(
    'CredenzaBody',
    DialogBody,
    DrawerBody
)

const CredenzaFooter = credenzaPart<React.ComponentPropsWithoutRef<'div'>, HTMLDivElement>(
    'CredenzaFooter',
    DialogFooter,
    DrawerFooter
)

const CredenzaClose = credenzaPart<React.ComponentPropsWithoutRef<typeof DialogClose>, HTMLButtonElement>(
    'CredenzaClose',
    DialogClose,
    DrawerClose
)

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
