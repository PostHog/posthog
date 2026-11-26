import { type ReactNode, useLayoutEffect, useRef, useState } from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { fitCount } from './fitCount'

// Before an item has been on screen its width is unknown, so it is counted as about one filter pill wide.
const UNMEASURED_WIDTH_PX = 160
const MORE_WIDTH_PX = 96

export interface FitRowItem {
    id: string
    element: ReactNode
}

export function FitRow({ items }: { items: FitRowItem[] }): JSX.Element {
    const rowRef = useRef<HTMLDivElement>(null)
    const elements = useRef(new Map<string, HTMLElement>())
    // Kept for items in the popover too, so the row knows whether one would fit back in without showing it first.
    const widths = useRef(new Map<string, number>())
    const [available, setAvailable] = useState(0)
    const [shown, setShown] = useState(items.length)

    useLayoutEffect(() => {
        const row = rowRef.current
        if (!row) {
            return
        }
        const observer = new ResizeObserver(([entry]) => setAvailable(entry.contentRect.width))
        observer.observe(row)
        return () => observer.disconnect()
    }, [])

    useLayoutEffect(() => {
        elements.current.forEach((element, id) => widths.current.set(id, element.offsetWidth))
        const fit = fitCount(
            items.map((item) => widths.current.get(item.id) ?? UNMEASURED_WIDTH_PX),
            available,
            MORE_WIDTH_PX
        )
        setShown(available > 0 ? fit : items.length)
        // An item's content can change its width, and an item back from the popover is measured once it shows.
    }, [items, available, shown])

    const hidden = items.slice(shown)
    return (
        <div ref={rowRef} className="flex min-w-0 flex-1 items-center gap-2">
            {items.slice(0, shown).map((item) => (
                <div
                    key={item.id}
                    className="shrink-0"
                    ref={(element) => {
                        if (element) {
                            elements.current.set(item.id, element)
                        } else {
                            elements.current.delete(item.id)
                        }
                    }}
                >
                    {item.element}
                </div>
            ))}
            {hidden.length > 0 && (
                <Popover>
                    <PopoverTrigger
                        render={
                            <Button
                                size="sm"
                                variant="outline"
                                className="shrink-0"
                                data-attr="dashboard-v2-more-filters"
                            />
                        }
                    >
                        +{hidden.length} {hidden.length === 1 ? 'filter' : 'filters'}
                    </PopoverTrigger>
                    <PopoverContent align="start" className="flex flex-col items-start gap-2 p-2">
                        {hidden.map((item) => (
                            <div key={item.id}>{item.element}</div>
                        ))}
                    </PopoverContent>
                </Popover>
            )}
        </div>
    )
}
