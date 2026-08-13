import { useEffect, useRef, useState } from 'react'

import { IconChevronRight, IconEllipsis } from '@posthog/icons'
import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { pluralize } from 'lib/utils/strings'

interface DashboardSectionHeaderProps {
    group: DashboardGroupApi
    collapsed: boolean
    onToggle: () => void
    onRename: (name: string) => void
    onMove: (position: number) => void
    onDelete: (memberHandling: 'delete_tiles' | 'ungroup') => void
    tileCount: number
    sectionCount: number
}

export function DashboardSectionHeader({
    group,
    collapsed,
    onToggle,
    onRename,
    onMove,
    onDelete,
    tileCount,
    sectionCount,
}: DashboardSectionHeaderProps): JSX.Element {
    const [editing, setEditing] = useState(false)
    const [name, setName] = useState(group.name ?? '')
    const dragStart = useRef<{ pointerId: number; y: number; headerHeight: number } | null>(null)
    const [dragOffset, setDragOffset] = useState<number | null>(null)

    useEffect(() => {
        const handlePointerMove = (event: PointerEvent): void => {
            if (!dragStart.current || event.pointerId !== dragStart.current.pointerId) {
                return
            }
            setDragOffset(event.clientY - dragStart.current.y)
        }
        const handlePointerUp = (event: PointerEvent): void => {
            if (!dragStart.current || event.pointerId !== dragStart.current.pointerId) {
                return
            }
            const offset = event.clientY - dragStart.current.y
            const positionDelta = Math.round(offset / dragStart.current.headerHeight)
            if (positionDelta !== 0) {
                onMove(Math.max(0, Math.min(sectionCount - 1, group.position + positionDelta)))
            }
            dragStart.current = null
            setDragOffset(null)
        }
        window.addEventListener('pointermove', handlePointerMove)
        window.addEventListener('pointerup', handlePointerUp)
        window.addEventListener('pointercancel', handlePointerUp)
        return () => {
            window.removeEventListener('pointermove', handlePointerMove)
            window.removeEventListener('pointerup', handlePointerUp)
            window.removeEventListener('pointercancel', handlePointerUp)
        }
    }, [group.position, onMove, sectionCount])

    const submitRename = (): void => {
        const trimmedName = name.trim()
        setEditing(false)
        if (trimmedName && trimmedName !== group.name) {
            onRename(trimmedName)
        }
    }

    return (
        <div
            className="flex items-center gap-2 px-3 py-2 cursor-grab"
            onPointerDown={(event) => {
                if ((event.target as Element).closest('button,input')) {
                    return
                }
                dragStart.current = {
                    pointerId: event.pointerId,
                    y: event.clientY,
                    headerHeight: event.currentTarget.getBoundingClientRect().height,
                }
            }}
        >
            <LemonButton
                icon={<IconChevronRight className={collapsed ? '' : 'rotate-90'} />}
                size="small"
                onClick={onToggle}
                tooltip={collapsed ? 'Expand section' : 'Collapse section'}
                data-attr="dashboard-section-collapse"
            />
            {editing ? (
                <LemonInput
                    autoFocus
                    value={name}
                    onChange={setName}
                    onBlur={submitRename}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            submitRename()
                        }
                        if (event.key === 'Escape') {
                            setName(group.name ?? '')
                            setEditing(false)
                        }
                    }}
                />
            ) : (
                <h4 className="font-semibold mb-0">{group.name}</h4>
            )}
            <span className="text-muted text-sm">{pluralize(tileCount, 'tile')}</span>
            <div className="ml-auto">
                <LemonMenu
                    items={[
                        { label: 'Rename', onClick: () => setEditing(true) },
                        {
                            label: 'Move up',
                            disabledReason: group.position === 0 ? 'This section is first' : undefined,
                            onClick: () => onMove(group.position - 1),
                        },
                        {
                            label: 'Move down',
                            disabledReason: group.position === sectionCount - 1 ? 'This section is last' : undefined,
                            onClick: () => onMove(group.position + 1),
                        },
                        {
                            label: 'Delete',
                            status: 'danger',
                            onClick: () =>
                                LemonDialog.open({
                                    title: 'Delete group?',
                                    description: `${pluralize(tileCount, 'tile')} will be affected.`,
                                    primaryButton: {
                                        children: 'Delete group and tiles',
                                        status: 'danger',
                                        onClick: () => onDelete('delete_tiles'),
                                    },
                                    secondaryButton: { children: 'Ungroup', onClick: () => onDelete('ungroup') },
                                    tertiaryButton: { children: 'Cancel' },
                                }),
                        },
                    ]}
                >
                    <LemonButton icon={<IconEllipsis />} size="small" data-attr="dashboard-section-menu" />
                </LemonMenu>
            </div>
            {dragOffset !== null && Math.abs(dragOffset) > 4 && (
                <>
                    <div
                        className="fixed left-4 right-4 z-[var(--z-modal)] h-0.5 bg-accent pointer-events-none"
                        style={{ top: group.position * 40 + dragOffset }}
                    />
                    <div
                        className="fixed z-[var(--z-modal)] rounded border border-accent bg-surface-primary px-3 py-2 shadow pointer-events-none"
                        style={{ left: 24, top: dragStart.current!.y + dragOffset }}
                    >
                        {group.name}
                    </div>
                </>
            )}
        </div>
    )
}
