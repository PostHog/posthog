import { useLayoutEffect, useRef } from 'react'

import { LemonTable, LemonTableProps } from 'lib/lemon-ui/LemonTable'

export function ModelsOverviewTable<T extends Record<string, any>>({
    'data-attr': dataAttr,
    ...props
}: LemonTableProps<T>): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const contentRef = useRef<HTMLDivElement>(null)
    const hasMultiplePages = props.dataSource.length > 10

    useLayoutEffect(() => {
        const container = containerRef.current
        const content = contentRef.current
        if (!container || !content || !hasMultiplePages) {
            container?.style.removeProperty('min-height')
            return
        }
        let height = 0
        const preserveHeight = (): void => {
            const bounds = content.getBoundingClientRect()
            height = Math.max(height, bounds.height)
            container.style.minHeight = `${height}px`
        }
        preserveHeight()
        const observer = new ResizeObserver(preserveHeight)
        observer.observe(content)
        return () => observer.disconnect()
    }, [hasMultiplePages])

    return (
        <div ref={containerRef} data-attr={dataAttr}>
            <div ref={contentRef}>
                <LemonTable {...props} scrollToTopOnPageChange={false} pagination={{ pageSize: 10, useUrl: false }} />
            </div>
        </div>
    )
}
