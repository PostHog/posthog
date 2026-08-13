import { HTMLAttributes, ForwardedRef, MouseEventHandler, forwardRef, useEffect, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { pluralize } from 'lib/utils/strings'

interface DashboardGroupItemProps extends HTMLAttributes<HTMLDivElement> {
    group: DashboardGroupApi
    collapsed: boolean
    onToggle: () => void
    showActions: boolean
    compact: boolean
    onDragHandleMouseDown?: MouseEventHandler<HTMLDivElement>
    onRename: (name: string) => Promise<void>
    onDelete: () => void
}

function DashboardGroupItemInternal(
    {
        group,
        collapsed,
        onToggle,
        showActions,
        compact,
        onDragHandleMouseDown,
        onRename,
        onDelete,
        className,
        style,
        onMouseDown: onGridMouseDown,
        ...props
    }: DashboardGroupItemProps,
    ref: ForwardedRef<HTMLDivElement>
): JSX.Element {
    const [name, setName] = useState(group.name)
    const [saving, setSaving] = useState(false)
    const [renaming, setRenaming] = useState(false)

    useEffect(() => setName(group.name), [group.name])

    const saveName = async (): Promise<void> => {
        const trimmedName = name.trim()
        if (saving || trimmedName === group.name) {
            setName(group.name)
            setRenaming(false)
            return
        }
        if (!trimmedName) {
            setName(group.name)
            setRenaming(false)
            return
        }
        setSaving(true)
        try {
            await onRename(trimmedName)
            setRenaming(false)
        } finally {
            setSaving(false)
        }
    }

    return (
        <div
            ref={ref}
            className={`${className ?? ''} DashboardGroupItem DashboardTileCard ${compact ? 'DashboardGroupItem--compact' : ''}`}
            style={style}
            data-attr="dashboard-group"
            data-group-id={group.id}
            onMouseDown={onGridMouseDown}
            {...props}
        >
            <CardMeta
                className="drag-handle"
                onMouseDown={onDragHandleMouseDown}
                showEditingControls={showActions}
                moreButtons={
                    <>
                        <LemonButton fullWidth onClick={() => setRenaming(true)}>
                            Rename
                        </LemonButton>
                        <LemonButton status="danger" fullWidth onClick={onDelete}>
                            Delete
                        </LemonButton>
                    </>
                }
                headerContent={
                    <div className="flex min-w-0 items-center gap-1">
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={
                                <IconChevronRight
                                    className={`transition-transform duration-200 ${collapsed ? '' : 'rotate-90'}`}
                                />
                            }
                            onClick={onToggle}
                            aria-label={collapsed ? `Expand ${group.name}` : `Collapse ${group.name}`}
                        />
                        {renaming ? (
                            <LemonInput
                                className="min-w-0 flex-1"
                                size="small"
                                value={name}
                                disabled={saving}
                                onChange={setName}
                                onBlur={saveName}
                                stopPropagation
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter') {
                                        event.currentTarget.blur()
                                    }
                                    if (event.key === 'Escape') {
                                        setName(group.name)
                                        setRenaming(false)
                                        event.currentTarget.blur()
                                    }
                                }}
                                aria-label="Group name"
                            />
                        ) : (
                            <button
                                type="button"
                                className="min-w-0 max-w-full cursor-text appearance-none border-0 bg-transparent p-0 text-left font-inherit text-inherit hover:underline disabled:cursor-default disabled:no-underline disabled:opacity-100"
                                onClick={() => setRenaming(true)}
                                disabled={!showActions}
                            >
                                <h4 className="mb-0 truncate font-semibold">{group.name}</h4>
                            </button>
                        )}
                        <span className="shrink-0 text-xs text-secondary">
                            {pluralize(group.member_tile_ids.length, 'tile')}
                        </span>
                    </div>
                }
            />
        </div>
    )
}

export const DashboardGroupItem = forwardRef<HTMLDivElement, DashboardGroupItemProps>(DashboardGroupItemInternal)

DashboardGroupItem.displayName = 'DashboardGroupItem'
