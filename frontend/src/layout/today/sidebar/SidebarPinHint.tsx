import { useEffect, useId, useState } from 'react'

import { IconX } from '@posthog/icons'
import {
    Button,
    Card,
    CardAction,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Popover,
    PopoverContent,
} from '@posthog/quill'

/** Points at a row's menu to show where an item is pinned from. A click anywhere closes it, the menu too. */
export function SidebarPinHint({
    anchor,
    onClose,
    dataAttr,
}: {
    anchor: Element
    onClose: () => void
    dataAttr: string
}): JSX.Element {
    const id = useId()
    const [open, setOpen] = useState(false)

    useEffect(() => {
        // The menu column sits at the table's far edge, off screen in a narrow scene.
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
        anchor.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: reduceMotion ? 'auto' : 'smooth' })
        // A popover that mounts open skips its entrance, so it mounts closed and opens straight after.
        setOpen(true)
    }, [anchor])

    return (
        <Popover open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
            <PopoverContent
                anchor={anchor}
                side="left"
                align="center"
                sideOffset={8}
                initialFocus={false}
                finalFocus={false}
                aria-labelledby={`${id}-title`}
                aria-describedby={`${id}-description`}
                // The card draws the surface, so the popover only places and animates it.
                className="w-72 gap-0 border-0 bg-transparent p-0 shadow-none"
                data-attr={dataAttr}
            >
                <Card className="border border-[var(--border)] shadow-[var(--shadow-md)]">
                    <CardHeader>
                        <CardTitle id={`${id}-title`}>Pin items to your sidebar</CardTitle>
                        <CardDescription id={`${id}-description`}>
                            Open this menu on an item, then select Pin to sidebar.
                        </CardDescription>
                        <CardAction>
                            <Button size="icon-sm" aria-label="Close" onClick={onClose} data-attr={`${dataAttr}-close`}>
                                <IconX />
                            </Button>
                        </CardAction>
                    </CardHeader>
                    <CardFooter className="justify-end">
                        <Button variant="primary" onClick={onClose} data-attr={`${dataAttr}-done`}>
                            Got it
                        </Button>
                    </CardFooter>
                </Card>
            </PopoverContent>
        </Popover>
    )
}
