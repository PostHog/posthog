import { HTMLAttributes, forwardRef } from 'react'

import { IconChevronRight, IconEllipsis } from '@posthog/icons'
import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

interface DashboardGroupItemProps extends HTMLAttributes<HTMLDivElement> {
    group: DashboardGroupApi
    collapsed: boolean
    onToggle: () => void
    editing: boolean
    onRename: () => void
    onDelete: () => void
}

export const DashboardGroupItem = forwardRef<HTMLDivElement, DashboardGroupItemProps>(
    ({ group, collapsed, onToggle, editing, onRename, onDelete, className, style, ...props }, ref) => (
        <div
            ref={ref}
            className={`${className ?? ''} drag-handle flex items-center gap-2 rounded border bg-surface-primary px-3`}
            style={style}
            data-attr="dashboard-group"
            data-group-id={group.id}
            {...props}
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconChevronRight className={collapsed ? '' : 'rotate-90'} />}
                onClick={onToggle}
                aria-label={collapsed ? `Expand ${group.name}` : `Collapse ${group.name}`}
            />
            <strong className="truncate">{group.name}</strong>
            <span className="text-secondary">({group.member_tile_ids.length} tiles)</span>
            {editing && (
                <LemonMenu
                    items={[
                        { label: 'Rename', onClick: onRename },
                        { label: 'Delete', status: 'danger', onClick: onDelete },
                    ]}
                >
                    <LemonButton
                        className="ml-auto"
                        size="xsmall"
                        type="tertiary"
                        icon={<IconEllipsis />}
                        aria-label={`Edit ${group.name}`}
                    />
                </LemonMenu>
            )}
        </div>
    )
)

DashboardGroupItem.displayName = 'DashboardGroupItem'
