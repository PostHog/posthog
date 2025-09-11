import { DndContext, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement } from '@dnd-kit/modifiers'
import { SortableContext, rectSortingStrategy } from '@dnd-kit/sortable'
import { useEffect, useState } from 'react'

import { PathCleaningFilter } from '~/types'

import { PathCleanFilterAddItemButton } from './PathCleanFilterAddItemButton'
import { PathCleanFilterItem } from './PathCleanFilterItem'
import { ensureFilterOrder, updateFilterOrder } from './pathCleaningUtils'

export interface PathCleanFiltersProps {
    filters?: PathCleaningFilter[]
    setFilters: (filters: PathCleaningFilter[]) => void
}

export const keyFromFilter = (filter: PathCleaningFilter): string => {
    return `${filter.alias}-${filter.regex}`
}

export function PathCleanFilters({ filters = [], setFilters }: PathCleanFiltersProps): JSX.Element {
    const [localFilters, setLocalFilters] = useState(filters)

    useEffect(() => {
        setLocalFilters(ensureFilterOrder(filters))
    }, [filters])

    const updateFilters = (newFilters: PathCleaningFilter[]): void => {
        const filtersWithOrder = updateFilterOrder(newFilters)
        setLocalFilters(filtersWithOrder)
        setFilters(filtersWithOrder)
    }

    const onAddFilter = (filter: PathCleaningFilter): void => {
        const filterWithOrder = {
            ...filter,
            order: filters.length,
        }
        updateFilters([...filters, filterWithOrder])
    }

    const onEditFilter = (index: number, filter: PathCleaningFilter): void => {
        const newFilters = filters.map((f, i) => (i === index ? filter : f))
        updateFilters(newFilters)
    }

    const onRemoveFilter = (index: number): void => {
        updateFilters(filters.filter((_, i) => i !== index))
    }

    const onSortEnd = ({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void => {
        function move(arr: PathCleaningFilter[], from: number, to: number): PathCleaningFilter[] {
            const clone = [...arr]
            Array.prototype.splice.call(clone, to, 0, Array.prototype.splice.call(clone, from, 1)[0])
            return clone
        }
        updateFilters(move(localFilters, oldIndex, newIndex))
    }

    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 1 } }))

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <DndContext
                    onDragEnd={({ active, over }) => {
                        if (!over || active.id === over.id) {
                            return
                        }

                        const aliases = localFilters.map((filter) => filter.alias)
                        onSortEnd({
                            oldIndex: aliases.indexOf(String(active.id)),
                            newIndex: aliases.indexOf(String(over.id)),
                        })
                    }}
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    modifiers={[restrictToParentElement]}
                >
                    <SortableContext items={localFilters.map(keyFromFilter)} strategy={rectSortingStrategy}>
                        {localFilters.map((filter, index) => (
                            <PathCleanFilterItem
                                key={keyFromFilter(filter)}
                                filter={filter}
                                onChange={(filter) => onEditFilter(index, filter)}
                                onRemove={() => onRemoveFilter(index)}
                            />
                        ))}
                    </SortableContext>
                </DndContext>
            </div>
            <div>
                <PathCleanFilterAddItemButton onAdd={onAddFilter} />
            </div>
        </div>
    )
}
