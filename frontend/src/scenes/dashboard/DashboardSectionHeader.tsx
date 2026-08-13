import clsx from 'clsx'
import { useState, type PointerEvent } from 'react'

import { IconChevronRight, IconEllipsis } from '@posthog/icons'
import type {
    DashboardGroupApi,
    MemberHandlingEnumApi,
} from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { pluralize } from 'lib/utils/strings'

import { sectionDisplayName } from './dashboardSections'

export interface DashboardSectionHeaderProps {
    group: DashboardGroupApi
    collapsed: boolean
    canEdit: boolean
    groupCount: number
    tileCount: number
    onToggle: () => void
    onRename: (name: string) => void
    onMove: (position: number) => void
    onDelete: (memberHandling: MemberHandlingEnumApi) => void
    onSectionPointerDown?: (event: PointerEvent<HTMLDivElement>) => void
}

export function DashboardSectionHeader({
    group,
    collapsed,
    canEdit,
    groupCount,
    tileCount,
    onToggle,
    onRename,
    onMove,
    onDelete,
    onSectionPointerDown,
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

    return (
        <div
            className={clsx('flex items-center gap-2 px-3 py-2', onSectionPointerDown && 'cursor-grab touch-none')}
            onPointerDown={onSectionPointerDown}
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
                    data-attr="dashboard-section-rename-input"
                />
            ) : (
                <h4 className="font-semibold mb-0">{sectionDisplayName(group)}</h4>
            )}
            <span className="text-muted text-sm">{pluralize(tileCount, 'tile')}</span>
            {canEdit && (
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
                                disabledReason: group.position === groupCount - 1 ? 'This section is last' : undefined,
                                onClick: () => onMove(group.position + 1),
                            },
                            {
                                label: 'Delete',
                                status: 'danger',
                                onClick: () =>
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
                                    }),
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
