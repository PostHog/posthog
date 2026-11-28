import { ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { Button, Drawer, DrawerBody, DrawerClose, DrawerContent, DrawerHeader, DrawerTitle } from '@posthog/quill'

// Lemon popovers, modals and toasts portal to the body, outside the drawer. A click or Escape in one belongs to it.
const OUTSIDE_LAYER_SELECTOR = '.Popover, .LemonModal__container, .ReactModal__Overlay, .Toastify'

function isInOutsideLayer(target: EventTarget | null | undefined): boolean {
    return target instanceof Element && !!target.closest(OUTSIDE_LAYER_SELECTOR)
}

export interface PeekDrawerProps {
    open: boolean
    onClose: () => void
    title: ReactNode
    actions?: ReactNode
    subheader?: ReactNode
    children: ReactNode
    'data-attr'?: string
}

export function PeekDrawer({
    open,
    onClose,
    title,
    actions,
    subheader,
    children,
    'data-attr': dataAttr,
}: PeekDrawerProps): JSX.Element {
    return (
        <Drawer
            open={open}
            swipeDirection="right"
            // Not modal, so a Lemon popover the content opens can still take focus.
            modal={false}
            onOpenChange={(nextOpen, details) => {
                if (!nextOpen && !isInOutsideLayer(details.event?.target)) {
                    onClose()
                }
            }}
        >
            <DrawerContent
                backdrop={false}
                // The quill default of 24rem is a menu's width; an item page needs half the window, as the logs drawer had.
                className="w-[max(50vw,min(36rem,100vw))] max-w-full"
                data-attr={dataAttr}
                data-item-peek-root
            >
                <DrawerHeader className="gap-2 border-b">
                    <div className="flex items-center gap-1">
                        <DrawerTitle className="min-w-0 flex-1 truncate">{title}</DrawerTitle>
                        <div className="flex shrink-0 flex-wrap items-center gap-1">
                            {actions}
                            <DrawerClose
                                render={<Button size="icon-sm" aria-label="Close" data-attr="peek-drawer-close" />}
                            >
                                <IconX />
                            </DrawerClose>
                        </div>
                    </div>
                    {subheader && <div data-not-quill>{subheader}</div>}
                </DrawerHeader>
                {/* The quill bridge maps Lemon color tokens to quill's palette inside the portal, which turns Lemon surfaces brand-colored. */}
                <DrawerBody className="py-4">
                    <div data-not-quill>{children}</div>
                </DrawerBody>
            </DrawerContent>
        </Drawer>
    )
}
