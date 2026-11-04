import { ReactNode, useLayoutEffect, useRef, useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Badge, Button, Separator, Text, cn } from '@posthog/quill'

export interface ChartOptionPage {
    key: string
    title: string
    // Options on the page set away from their default, shown on its row so none goes unnoticed.
    count: number
    content: ReactNode
}

export interface QuillChartOptionPagesProps {
    home: ReactNode
    pages: ChartOptionPage[]
    className?: string
    'data-attr'?: string
}

export function QuillChartOptionPages({
    home,
    pages,
    className,
    'data-attr': dataAttr,
}: QuillChartOptionPagesProps): JSX.Element {
    const [openKey, setOpenKey] = useState<string | null>(null)
    const backRef = useRef<HTMLButtonElement>(null)
    const rowRefs = useRef(new Map<string, HTMLButtonElement>())
    const returnFocusKey = useRef<string | null>(null)
    // A chart type change can remove the open page, so fall back to the list.
    const openPage = pages.find((page) => page.key === openKey)
    // Callers rebuild `pages` on every render, so focus follows the key, not the page object.
    const openPageKey = openPage?.key ?? null

    useLayoutEffect(() => {
        if (openPageKey) {
            backRef.current?.focus()
        } else if (returnFocusKey.current) {
            rowRefs.current.get(returnFocusKey.current)?.focus()
            returnFocusKey.current = null
        }
    }, [openPageKey])

    const goBack = (): void => {
        returnFocusKey.current = openKey
        setOpenKey(null)
    }

    if (openPage) {
        return (
            <div className={cn('flex flex-col gap-2', className)} data-attr={dataAttr}>
                <div className="-ms-1 flex items-center gap-1">
                    <Button
                        ref={backRef}
                        size="icon-sm"
                        aria-label="Back to all options"
                        tooltip="Back to all options"
                        onClick={goBack}
                        data-attr="chart-option-pages-back"
                    >
                        <IconChevronLeft />
                    </Button>
                    <Text size="sm" weight="semibold" render={<span />} className="min-w-0 truncate">
                        {openPage.title}
                    </Text>
                </div>
                <div className="flex flex-col gap-2" data-attr={`chart-option-page-${openPage.key}`}>
                    {openPage.content}
                </div>
            </div>
        )
    }

    return (
        <div className={cn('flex flex-col gap-2', className)} data-attr={dataAttr}>
            {home}
            {pages.length > 0 && (
                <>
                    {home && <Separator />}
                    <div className="flex flex-col">
                        {pages.map((page) => (
                            <Button
                                key={page.key}
                                ref={(node) => {
                                    if (node) {
                                        rowRefs.current.set(page.key, node)
                                    } else {
                                        rowRefs.current.delete(page.key)
                                    }
                                }}
                                size="row"
                                left
                                // Bleeds into the panel's padding so the row text lines up with the option labels.
                                className="-mx-2 w-auto"
                                aria-label={page.count > 0 ? `${page.title}, ${page.count} changed` : page.title}
                                onClick={() => setOpenKey(page.key)}
                                data-attr={`chart-option-page-row-${page.key}`}
                            >
                                <span className="min-w-0 truncate">{page.title}</span>
                                {page.count > 0 && (
                                    <Badge className="ml-auto" aria-hidden>
                                        {page.count}
                                    </Badge>
                                )}
                                <IconChevronRight
                                    className={cn('text-muted-foreground', page.count === 0 && 'ml-auto')}
                                />
                            </Button>
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}
