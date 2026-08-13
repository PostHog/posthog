import clsx from 'clsx'
import { ComponentProps, PointerEvent, ReactNode } from 'react'
import { Responsive as ReactGridLayout } from 'react-grid-layout'
import { GridBackground } from 'react-grid-layout/extras'

import type {
    DashboardGroupApi,
    MemberHandlingEnumApi,
} from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { DashboardSectionHeader } from './DashboardSectionHeader'

export interface DashboardSectionProps {
    group: DashboardGroupApi | null
    collapsed: boolean
    canEdit: boolean
    groupCount: number
    tileCount: number
    children: ReactNode
    overlay: ReactNode
    sectionRef?: (element: HTMLElement | null) => void
    highlighted?: boolean
    onSectionPointerDown?: (event: PointerEvent<HTMLDivElement>) => void
    gridProps: ComponentProps<typeof ReactGridLayout>
    gridBackgroundProps: ComponentProps<typeof GridBackground> | null
    onToggle: () => void
    onRename: (name: string) => void
    onMove: (position: number) => void
    onDelete: (memberHandling: MemberHandlingEnumApi) => void
}

export function DashboardSection({
    group,
    collapsed,
    canEdit,
    groupCount,
    tileCount,
    children,
    overlay,
    sectionRef,
    highlighted = false,
    onSectionPointerDown,
    gridProps,
    gridBackgroundProps,
    onToggle,
    onRename,
    onMove,
    onDelete,
}: DashboardSectionProps): JSX.Element {
    return (
        <section
            ref={sectionRef}
            className={clsx(
                'relative mb-4',
                group && "rounded border bg-surface-tertiary [[theme='dark']_&]:bg-surface-secondary border-primary",
                highlighted && 'border-accent bg-accent-highlight-secondary'
            )}
        >
            {group && (
                <DashboardSectionHeader
                    group={group}
                    collapsed={collapsed}
                    canEdit={canEdit}
                    groupCount={groupCount}
                    tileCount={tileCount}
                    onToggle={onToggle}
                    onRename={onRename}
                    onMove={onMove}
                    onDelete={onDelete}
                    onSectionPointerDown={onSectionPointerDown}
                />
            )}
            {!collapsed && (
                <div className={clsx('relative', group && 'px-3')}>
                    {gridBackgroundProps && <GridBackground {...gridBackgroundProps} />}
                    <ReactGridLayout {...gridProps}>{children}</ReactGridLayout>
                    {overlay}
                </div>
            )}
        </section>
    )
}
