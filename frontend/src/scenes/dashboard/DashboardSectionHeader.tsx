import { type PointerEvent as ReactPointerEvent, useState } from 'react'

import { IconChevronRight, IconEllipsis, IconPlusSmall } from '@posthog/icons'
import type {
    DashboardGroupApi,
    MemberHandlingEnumApi,
} from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { IconDragHandle } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { pluralize } from 'lib/utils/strings'

import { sectionDisplayName } from './dashboardSections'

export interface DashboardSectionHeaderProps {
    group: DashboardGroupApi
    collapsed: boolean
    canEdit: boolean
    tileCount: number
    addMenuItems?: LemonMenuItems
    onToggle: () => void
    onRename: (name: string) => void
    onDelete: (memberHandling: MemberHandlingEnumApi) => void
    onDragStart?: (event: ReactPointerEvent<HTMLDivElement>) => void
}

export function DashboardSectionHeader({
    group,
    collapsed,
    canEdit,
    tileCount,
    addMenuItems,
    onToggle,
    onRename,
    onDelete,
    onDragStart,
}: DashboardSectionHeaderProps): JSX.Element {
    const [editing, setEditing] = useState(false)
    const [name, setName] = useState(group.name ?? '')

    const submitRename = (): void => {
        const trimmedName = name.trim()
        setEditing(false)
        if (trimmedName && trimmedName !== group.name) {
            onRename(trimmedName)
        } else {
            setName(group.name ?? '')
        }
    }

    const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>): void => {
        const target = event.target as Element
        if (target.closest('button,input,textarea,select,[contenteditable="true"]')) {
            return
        }
        onDragStart?.(event)
    }

    return (
        <div
            className={
                canEdit
                    ? 'flex cursor-grab items-center gap-2 rounded-t bg-surface-primary px-3 py-2'
                    : 'flex items-center gap-2 rounded-t bg-surface-primary px-3 py-2'
            }
            data-attr="dashboard-section-header"
            onPointerDown={canEdit ? handlePointerDown : undefined}
        >
            {canEdit && (
                <span
                    className="dashboard-section-drag-handle cursor-grab touch-none text-muted"
                    data-attr="dashboard-section-drag-handle"
                >
                    <IconDragHandle />
                </span>
            )}
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
                    data-attr="dashboard-section-rename-input"
                />
            ) : (
                <h4 className="mb-0">
                    <button
                        type="button"
                        className="cursor-pointer font-semibold text-left"
                        data-attr="dashboard-section-name"
                        disabled={!canEdit}
                        onClick={() => {
                            setName(group.name ?? '')
                            setEditing(true)
                        }}
                    >
                        {sectionDisplayName(group)}
                    </button>
                </h4>
            )}
            <span className="text-muted text-sm">{pluralize(tileCount, 'tile')}</span>
            {canEdit && (
                <div className="ml-auto flex items-center gap-1">
                    {addMenuItems && (
                        <LemonMenu items={addMenuItems}>
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconPlusSmall />}
                                tooltip="Add"
                                data-attr="dashboard-section-add-tile"
                            />
                        </LemonMenu>
                    )}
                    <LemonMenu
                        items={[
                            {
                                label: 'Delete',
                                status: 'danger',
                                onClick: () => {
                                    if (tileCount === 0) {
                                        onDelete('delete_tiles')
                                        return
                                    }
                                    LemonDialog.open({
                                        title: 'Delete section?',
                                        description:
                                            'Delete the section and its tiles, or ungroup to keep the tiles without a heading.',
                                        primaryButton: {
                                            children: 'Delete section and tiles',
                                            status: 'danger',
                                            onClick: () => onDelete('delete_tiles'),
                                        },
                                        secondaryButton: {
                                            children: 'Ungroup',
                                            onClick: () => onDelete('ungroup'),
                                        },
                                        tertiaryButton: { children: 'Cancel' },
                                    })
                                },
                            },
                        ]}
                    >
                        <LemonButton icon={<IconEllipsis />} size="small" data-attr="dashboard-section-menu" />
                    </LemonMenu>
                </div>
            )}
        </div>
    )
}
