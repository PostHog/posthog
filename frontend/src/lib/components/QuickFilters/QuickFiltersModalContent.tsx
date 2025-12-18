import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumn, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { QuickFilter, QuickFilterOption } from '~/types'

import { QuickFiltersLogicProps, quickFiltersLogic } from './quickFiltersLogic'
import { quickFiltersModalLogic } from './quickFiltersModalLogic'

export function QuickFiltersModalContent({ context }: QuickFiltersLogicProps): JSX.Element {
    const { quickFilters, quickFiltersLoading } = useValues(quickFiltersLogic({ context }))
    const { startAddNew, startEdit, confirmDelete } = useActions(quickFiltersModalLogic({ context }))

    return (
        <div className="space-y-4">
            <p className="text-muted">
                Quick filters let you create reusable filter components for specific event properties.
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
                    <LemonTable
                        dataSource={quickFilters}
                        loading={quickFiltersLoading}
                        columns={
                            [
                                {
                                    title: 'Name',
                                    dataIndex: 'name',
                                    render: (name) => <div className="font-medium">{name}</div>,
                                },
                                {
                                    title: 'Property',
                                    dataIndex: 'property_name',
                                    render: (path) => <code className="text-xs">{path}</code>,
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
                                                    <span className="px-2 py-0.5 bg-border rounded text-xs">
                                                        +{options.length - 3} more
                                                    </span>
                                                </Tooltip>
                                            )}
                                        </div>
                                    ),
                                },
                                {
                                    title: 'Updated',
                                    dataIndex: 'updated_at',
                                    render: (date) => <TZLabel time={date} showPopover={false} />,
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
                            ] as LemonTableColumn<QuickFilter, any>[]
                        }
                    />
                    <div className="flex justify-end mt-4">
                        <LemonButton type="primary" icon={<IconPlus />} onClick={startAddNew}>
                            Add filter
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
