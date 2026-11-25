import { DndContext, DragEndEvent, SensorDescriptor, SensorOptions, closestCenter } from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'

import {
    Empty,
    EmptyHeader,
    EmptyTitle,
    Table,
    TableBody,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill'

import { PathCleaningFilter } from '~/types'

import { QuillPathCleanFilterRow } from './QuillPathCleanFilterRow'

export function QuillPathCleanFiltersTable({
    filters,
    sensors,
    restrictedReason,
    onDragStart,
    onDragEnd,
    onEditFilter,
    onRemoveFilter,
}: {
    filters: PathCleaningFilter[]
    sensors: SensorDescriptor<SensorOptions>[]
    restrictedReason: string | null
    onDragStart: () => void
    onDragEnd: (event: DragEndEvent) => void
    onEditFilter: (index: number, filter: PathCleaningFilter) => void
    onRemoveFilter: (index: number) => void
}): JSX.Element {
    return (
        <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            modifiers={[restrictToVerticalAxis]}
        >
            <Table fullWidth tableClassName="table-fixed">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-10">
                            <span className="sr-only">Reorder</span>
                        </TableHead>
                        <TableHead className="w-16">Order</TableHead>
                        <TableHead>Regex Pattern</TableHead>
                        <TableHead>Alias</TableHead>
                        <TableHead className="w-24">Actions</TableHead>
                    </TableRow>
                </TableHeader>
                {filters.length === 0 ? (
                    <TableEmpty>
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>No path cleaning rules configured</EmptyTitle>
                            </EmptyHeader>
                        </Empty>
                    </TableEmpty>
                ) : (
                    <TableBody>
                        <SortableContext
                            items={filters.map((_, index) => `filter-${index}`)}
                            strategy={verticalListSortingStrategy}
                        >
                            {filters.map((filter, index) => (
                                <QuillPathCleanFilterRow
                                    key={`filter-${index}`}
                                    filter={filter}
                                    index={index}
                                    onEdit={(updatedFilter) => onEditFilter(index, updatedFilter)}
                                    onRemove={() => onRemoveFilter(index)}
                                    disabledReason={restrictedReason}
                                />
                            ))}
                        </SortableContext>
                    </TableBody>
                )}
            </Table>
        </DndContext>
    )
}
