import clsx from 'clsx'
import {
    type ComponentProps,
    type PointerEvent as ReactPointerEvent,
    type ReactNode,
    type TransitionEvent,
    useLayoutEffect,
    useRef,
    useState,
} from 'react'
import { createPortal } from 'react-dom'
import { Responsive as ReactGridLayout } from 'react-grid-layout'
import { GridBackground } from 'react-grid-layout/extras'

import type {
    DashboardGroupApi,
    MemberHandlingEnumApi,
} from '@posthog/products-dashboards/frontend/generated/api.schemas'

import type { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { DashboardSectionHeader } from './DashboardSectionHeader'
import type { DashboardSectionDragPreview } from './useCrossSectionDrag'

export interface DashboardSectionProps {
    group: DashboardGroupApi | null
    collapsed: boolean
    canEdit: boolean
    tileCount: number
    addMenuItems?: LemonMenuItems
    children: ReactNode
    overlay: ReactNode
    sectionRef?: (element: HTMLElement | null) => void
    sectionDragPreviewRef?: (element: HTMLElement | null) => void
    dragPreview?: DashboardSectionDragPreview
    showDropPreview?: boolean
    highlighted?: boolean
    gridProps: Omit<ComponentProps<typeof ReactGridLayout>, 'children'>
    gridBackgroundProps: ComponentProps<typeof GridBackground> | null
    onToggle: () => void
    onRename: (name: string) => void
    onDelete: (memberHandling: MemberHandlingEnumApi) => void
    onDragStart?: (event: ReactPointerEvent<HTMLDivElement>) => void
}

export function DashboardSection({
    group,
    collapsed,
    canEdit,
    tileCount,
    addMenuItems,
    children,
    overlay,
    sectionRef,
    sectionDragPreviewRef,
    dragPreview,
    showDropPreview = false,
    highlighted = false,
    gridProps,
    gridBackgroundProps,
    onToggle,
    onRename,
    onDelete,
    onDragStart,
}: DashboardSectionProps): JSX.Element {
    const [contentMounted, setContentMounted] = useState(!collapsed)
    const [contentHeight, setContentHeight] = useState<number | 'auto'>(collapsed ? 0 : 'auto')
    const contentRef = useRef<HTMLDivElement>(null)

    useLayoutEffect(() => {
        if (collapsed) {
            const height = contentRef.current?.scrollHeight ?? 0
            if (height === 0) {
                setContentMounted(false)
                return
            }
            setContentHeight(height)
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
                setContentMounted(false)
                return
            }
            const frame = requestAnimationFrame(() => setContentHeight(0))
            return () => cancelAnimationFrame(frame)
        }

        setContentMounted(true)
        setContentHeight(0)
        const frame = requestAnimationFrame(() => {
            const height = contentRef.current?.scrollHeight ?? 0
            setContentHeight(height === 0 ? 'auto' : height)
        })
        return () => cancelAnimationFrame(frame)
    }, [collapsed])

    const handleContentTransitionEnd = (event: TransitionEvent<HTMLDivElement>): void => {
        if (event.target !== event.currentTarget || event.propertyName !== 'height') {
            return
        }
        if (collapsed) {
            setContentMounted(false)
            return
        }
        setContentHeight('auto')
    }

    const sectionContent = (
        <section
            ref={dragPreview ? sectionDragPreviewRef : sectionRef}
            className={clsx(
                'mb-4',
                dragPreview ? 'fixed' : 'relative',
                group &&
                    "rounded border border-primary bg-surface-tertiary [[theme='dark']_&]:bg-surface-secondary ring-1 ring-primary",
                highlighted && 'border-accent bg-accent-highlight-secondary',
                dragPreview && 'pointer-events-none z-50 opacity-95 shadow-lg'
            )}
            style={
                dragPreview
                    ? {
                          height: dragPreview.height,
                          left: dragPreview.left,
                          top: dragPreview.top,
                          width: dragPreview.width,
                      }
                    : undefined
            }
        >
            {group && (
                <DashboardSectionHeader
                    group={group}
                    collapsed={collapsed}
                    canEdit={canEdit}
                    tileCount={tileCount}
                    addMenuItems={addMenuItems}
                    onToggle={onToggle}
                    onRename={onRename}
                    onDelete={onDelete}
                    onDragStart={onDragStart}
                />
            )}
            {highlighted && (
                <div className="pointer-events-none absolute inset-0 z-20 rounded border-2 border-dashed border-accent bg-accent-highlight-secondary/50" />
            )}
            {contentMounted && !dragPreview && (
                <div
                    className={clsx(
                        'transition-[height] duration-200 ease-in-out motion-reduce:transition-none',
                        contentHeight === 'auto' ? 'overflow-visible' : 'overflow-hidden'
                    )}
                    ref={contentRef}
                    style={{ height: contentHeight === 'auto' ? 'auto' : `${contentHeight}px` }}
                    onTransitionEnd={handleContentTransitionEnd}
                >
                    <div className={clsx('relative min-h-0', group && 'pt-2')}>
                        {gridBackgroundProps && <GridBackground {...gridBackgroundProps} />}
                        <ReactGridLayout {...gridProps} className={clsx('dashboard-section-grid', gridProps.className)}>
                            {children}
                        </ReactGridLayout>
                        {overlay}
                    </div>
                </div>
            )}
        </section>
    )

    if (!dragPreview) {
        return sectionContent
    }

    return (
        <div
            ref={sectionRef}
            className={clsx(
                'relative mb-4',
                showDropPreview && 'rounded border-2 border-dashed border-accent bg-accent-highlight-secondary/50'
            )}
            data-attr={showDropPreview ? 'dashboard-section-drop-preview' : undefined}
            style={{ height: dragPreview.height }}
        >
            {createPortal(sectionContent, document.body)}
        </div>
    )
}
