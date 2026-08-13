import { ComponentProps, ReactNode } from 'react'
import { Responsive as ReactGridLayout } from 'react-grid-layout'
import { GridBackground } from 'react-grid-layout/extras'

import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { DashboardSectionHeader } from './DashboardSectionHeader'

interface DashboardSectionProps {
    group: DashboardGroupApi | null
    collapsed: boolean
    editing: boolean
    children: ReactNode
    gridProps: ComponentProps<typeof ReactGridLayout>
    gridBackgroundProps: ComponentProps<typeof GridBackground> | null
    onToggle: () => void
    onRename: (name: string) => void
    onMove: (position: number) => void
    onDelete: (memberHandling: 'delete_tiles' | 'ungroup') => void
    tileCount: number
    sectionCount: number
    sectionRef: (element: HTMLElement | null) => void
    highlighted: boolean
    overlay: ReactNode
}

export function DashboardSection({
    group,
    collapsed,
    editing,
    children,
    gridProps,
    gridBackgroundProps,
    onToggle,
    onRename,
    onMove,
    onDelete,
    tileCount,
    sectionCount,
    sectionRef,
    highlighted,
    overlay,
}: DashboardSectionProps): JSX.Element {
    let sectionClassName = 'relative mb-4'
    if (group) {
        sectionClassName += " rounded border bg-surface-tertiary [[theme='dark']_&]:bg-surface-secondary border-primary"
    }
    if (highlighted) {
        sectionClassName += ' border-accent bg-accent-highlight-secondary'
    }

    return (
        <section ref={sectionRef} className={sectionClassName}>
            {group && (
                <DashboardSectionHeader
                    group={group}
                    collapsed={collapsed}
                    onToggle={onToggle}
                    onRename={onRename}
                    onMove={onMove}
                    onDelete={onDelete}
                    tileCount={tileCount}
                    sectionCount={sectionCount}
                />
            )}
            {!collapsed && (
                <div className="relative px-3">
                    {editing && gridBackgroundProps && <GridBackground {...gridBackgroundProps} />}
                    <ReactGridLayout {...gridProps}>{children}</ReactGridLayout>
                    {overlay}
                </div>
            )}
        </section>
    )
}
