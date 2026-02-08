import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonTable, LemonTableColumn, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter, QuickFilterOption } from '~/types'

import { quickFiltersLogic } from './quickFiltersLogic'
import { quickFiltersModalLogic } from './quickFiltersModalLogic'

interface SelectionColumnConfig {
    selectedIds: string[]
    onToggleId: (filterId: string) => void
}

interface FooterActionsConfig {
    onSaveSelection: () => void
    hasChanges: boolean
}

interface QuickFiltersModalContentProps {
    context: QuickFilterContext
    /** Key to scope modal logic instance (must match parent) */
    modalKey?: string | number
    /** Optional checkbox column for selecting which filters to show */
    selectionColumnConfig?: SelectionColumnConfig
    /** Optional footer actions (e.g. save selection) */
    footerActionsConfig?: FooterActionsConfig
}

export function QuickFiltersModalContent({
    context,
    modalKey,
    selectionColumnConfig,
    footerActionsConfig,
}: QuickFiltersModalContentProps): JSX.Element {
    const logic = quickFiltersModalLogic({ context, modalKey })
    const { quickFilters, quickFiltersLoading } = useValues(quickFiltersLogic({ context }))
    const { startAddNew, startEdit, confirmDelete, setSearchQuery } = useActions(logic)
    const { filteredQuickFilters, searchQuery } = useValues(logic)

    const columns: LemonTableColumn<QuickFilter, any>[] = [
        // Optional checkbox column for filter selection
        ...(selectionColumnConfig
            ? [
                  {
                      key: 'show',
                      title: 'Show',
                      width: 50,
                      render: (_: any, filter: QuickFilter) => (
                          <LemonCheckbox
                              checked={selectionColumnConfig.selectedIds.includes(filter.id)}
                              onChange={() => selectionColumnConfig.onToggleId(filter.id)}
                          />
                      ),
                      sorter: (a, b) => {
                          const aSelected = selectionColumnConfig.selectedIds.includes(a.id)
                          const bSelected = selectionColumnConfig.selectedIds.includes(b.id)
                          return Number(bSelected) - Number(aSelected)
                      },
                  } as LemonTableColumn<QuickFilter, any>,
              ]
            : []),
        {
            title: 'Filter name',
            dataIndex: 'name',
            render: (name) => <div className="font-medium">{name}</div>,
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Event property',
            dataIndex: 'property_name',
            render: (path) => <code className="text-xs">{path}</code>,
            sorter: (a, b) => a.property_name.localeCompare(b.property_name),
        },
        {
            title: 'Options',
            dataIndex: 'options',
            render: (options: QuickFilterOption[]) => (
                <div className="flex gap-1 flex-wrap">
                    {options.slice(0, 3).map((opt, index) => (
                        <span key={index} className="px-2 py-0.5 bg-border rounded text-xs">
                            {opt.label}
                        </span>
                    ))}
                    {options.length > 3 && (
                        <Tooltip
                            title={options
                                .slice(3)
                                .map((o) => o.label)
                                .join(', ')}
                        >
                            <span className="px-2 py-0.5 bg-border rounded text-xs">+{options.length - 3} more</span>
                        </Tooltip>
                    )}
                </div>
            ),
        },
        {
            title: 'Last updated',
            dataIndex: 'updated_at',
            render: (date) => <TZLabel time={date} showPopover={false} />,
            sorter: (a, b) => dayjs(a.updated_at).diff(b.updated_at),
        },
        {
            width: 0,
            render: (_, filter) => (
                <div className="flex gap-2">
                    <LemonButton size="small" onClick={() => startEdit(filter)}>
                        Edit
                    </LemonButton>
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => confirmDelete(filter.id)}
                    />
                </div>
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <p className="text-muted">
                Quick filters let you create reusable filter components for specific event properties.
                {selectionColumnConfig && ' Select the filters you want to show.'}
            </p>

            {quickFilters.length === 0 ? (
                <>
                    <div className="text-center py-8 text-muted">
                        <p>No quick filters yet.</p>
                        <p className="text-sm mt-2">
                            Create your first quick filter to quickly filter by specific properties.
                        </p>
                    </div>
                    <div className="flex justify-end">
                        <LemonButton type="primary" icon={<IconPlus />} onClick={startAddNew}>
                            Add filter
                        </LemonButton>
                    </div>
                </>
            ) : (
                <>
                    {quickFilters.length > 10 && (
                        <LemonInput
                            type="search"
                            placeholder="Search filters..."
                            value={searchQuery}
                            onChange={setSearchQuery}
                            className="mb-2"
                        />
                    )}
                    {filteredQuickFilters.length === 0 ? (
                        <div className="text-center py-8 text-muted">
                            <p>No filters match your search.</p>
                        </div>
                    ) : (
                        <LemonTable dataSource={filteredQuickFilters} loading={quickFiltersLoading} columns={columns} />
                    )}
                    <div className="flex justify-between mt-4">
                        {footerActionsConfig && (
                            <LemonButton
                                type="primary"
                                onClick={footerActionsConfig.onSaveSelection}
                                disabledReason={!footerActionsConfig.hasChanges ? 'No changes to save' : undefined}
                            >
                                Save selection
                            </LemonButton>
                        )}
                        <div className="flex-1" />
                        <LemonButton type="primary" icon={<IconPlus />} onClick={startAddNew}>
                            Add filter
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
