import { useLayoutEffect, useRef } from 'react'

import { LemonTable, LemonTableProps } from 'lib/lemon-ui/LemonTable'

export function ModelsOverviewTable<T extends Record<string, any>>({
    'data-attr': dataAttr,
    ...props
}: LemonTableProps<T>): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const contentRef = useRef<HTMLDivElement>(null)
    const preservedHeightRef = useRef(0)
    const hasMultiplePages = props.dataSource.length > 10

    useLayoutEffect(() => {
        const container = containerRef.current
        const content = contentRef.current
        if (!container || !content || props.loading) {
            return
        }
        if (!hasMultiplePages) {
            preservedHeightRef.current = 0
            container.style.removeProperty('min-height')
            return
        }
        const preserveHeight = (): void => {
            const bounds = content.getBoundingClientRect()
            preservedHeightRef.current = Math.max(preservedHeightRef.current, bounds.height)
            container.style.minHeight = `${preservedHeightRef.current}px`
        }
        preserveHeight()
        const observer = new ResizeObserver(preserveHeight)
        observer.observe(content)
        return () => observer.disconnect()
    }, [hasMultiplePages, props.loading])

    return (
        <div ref={containerRef} data-attr={dataAttr}>
            <div ref={contentRef}>
                <LemonTable {...props} scrollToTopOnPageChange={false} pagination={{ pageSize: 10, useUrl: false }} />
            </div>
        </div>
    )
}
