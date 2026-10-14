import { ReactNode, useMemo, useState } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { Button, Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '@posthog/quill'

import { TodaySheetMenuContext, TodaySheetMenuControls } from './todaySheetMenuContext'

interface TodaySheetMenuProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    title: string
    description?: string
    children: ReactNode
}

interface TodaySheetPage {
    id: string
    title: string
}

export function TodaySheetMenu({ open, onOpenChange, title, description, children }: TodaySheetMenuProps): JSX.Element {
    const [page, setPage] = useState<TodaySheetPage | null>(null)
    const [pageContainer, setPageContainer] = useState<HTMLElement | null>(null)

    const setOpen = (next: boolean): void => {
        if (!next) {
            setPage(null)
        }
        onOpenChange(next)
    }

    const controls = useMemo<TodaySheetMenuControls>(
        () => ({
            close: () => {
                setPage(null)
                onOpenChange(false)
            },
            back: () => setPage(null),
            openPage: (id, pageTitle) => setPage({ id, title: pageTitle }),
            activePageId: page?.id ?? null,
            pageContainer,
        }),
        [onOpenChange, page, pageContainer]
    )

    return (
        <Drawer open={open} onOpenChange={setOpen} swipeDirection="down">
            <DrawerContent data-attr="today-sheet-menu">
                <TodaySheetMenuContext.Provider value={controls}>
                    {page ? (
                        <DrawerHeader className="flex-row items-center gap-2">
                            <Button
                                size="icon"
                                aria-label="Back"
                                onClick={() => setPage(null)}
                                data-attr="today-sheet-menu-back"
                            >
                                <IconChevronLeft />
                            </Button>
                            <DrawerTitle className="min-w-0 flex-1 truncate">{page.title}</DrawerTitle>
                            <span aria-hidden className="size-7 shrink-0" />
                        </DrawerHeader>
                    ) : (
                        <DrawerHeader>
                            <DrawerTitle>{title}</DrawerTitle>
                            {description && <DrawerDescription>{description}</DrawerDescription>}
                        </DrawerHeader>
                    )}
                    <div className="flex min-h-0 flex-col overflow-y-auto px-2 pb-3" hidden={page !== null}>
                        {children}
                    </div>
                    <div
                        ref={setPageContainer}
                        className="flex min-h-0 flex-col overflow-y-auto px-2 pb-3"
                        hidden={page === null}
                    />
                </TodaySheetMenuContext.Provider>
            </DrawerContent>
        </Drawer>
    )
}
