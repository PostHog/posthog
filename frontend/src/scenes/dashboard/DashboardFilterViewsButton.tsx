import { useState } from 'react'

import { IconChevronDown, IconPlus } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { SavedViewsList } from 'lib/components/SavedViews/SavedViewsList'

import { DashboardFilterView } from '~/types'

export interface DashboardFilterViewsButtonProps {
    views: DashboardFilterView[]
    activeView?: DashboardFilterView
    hasUnsavedChanges?: boolean
    canEdit: boolean
    saving?: boolean
    defaultOpen?: boolean
    onCreate: () => void
    onSelect: (view: DashboardFilterView) => void
    onDelete: (view: DashboardFilterView) => void
    onEdit: (view: DashboardFilterView) => void
    onSaveChanges: (view: DashboardFilterView) => void
}

export function DashboardFilterViewsButton({
    views,
    activeView,
    hasUnsavedChanges,
    canEdit,
    saving,
    defaultOpen = false,
    onCreate,
    onSelect,
    onDelete,
    onEdit,
    onSaveChanges,
}: DashboardFilterViewsButtonProps): JSX.Element {
    const [visible, setVisible] = useState(defaultOpen)

    return (
        <Popover
            visible={visible}
            padded={false}
            onClickOutside={() => setVisible(false)}
            overlay={
                <div className="flex w-72 flex-col py-1" data-attr="dashboard-filter-views-popover">
                    {canEdit && activeView && hasUnsavedChanges && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="tertiary"
                            className="justify-start rounded-none px-3"
                            loading={saving}
                            onClick={() => onSaveChanges(activeView)}
                        >
                            Save changes to {activeView.name}
                        </LemonButton>
                    )}
                    {canEdit && views.length < 20 && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="tertiary"
                            className="justify-start rounded-none px-3"
                            icon={<IconPlus />}
                            loading={saving}
                            onClick={onCreate}
                        >
                            Save current filters
                        </LemonButton>
                    )}
                    {canEdit && views.length < 20 && <div className="border-t" />}
                    <SavedViewsList
                        views={[...views].sort((left, right) => left.name.localeCompare(right.name))}
                        activeViewId={activeView?.id}
                        emptyMessage="No saved filter views yet."
                        onSelect={(view) => {
                            onSelect(view)
                            setVisible(false)
                        }}
                        onDelete={canEdit ? onDelete : undefined}
                        onEdit={canEdit ? onEdit : undefined}
                    />
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                data-attr="dashboard-filter-views-picker"
                sideIcon={<IconChevronDown />}
                onClick={() => setVisible(!visible)}
            >
                {activeView ? `${activeView.name}${hasUnsavedChanges ? ' (edited)' : ''}` : 'Views'}
            </LemonButton>
        </Popover>
    )
}
