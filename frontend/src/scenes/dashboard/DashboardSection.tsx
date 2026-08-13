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
    overlay,
}: DashboardSectionProps): JSX.Element {
    return (
        <section
            className={
                group
                    ? "relative mb-4 rounded border border-primary bg-surface-tertiary [[theme='dark']_&]:bg-surface-secondary"
                    : 'relative mb-4'
            }
        >
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
