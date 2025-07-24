import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { arrayMove, SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { IconPencil, IconSort, IconTrash } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { isValidRegexp } from 'lib/utils/regexp'
import { useState } from 'react'

import { PathCleaningFilter } from '~/types'

import { PathRegexModal } from './PathRegexModal'
import { parseAliasToReadable } from './PathCleanFilterItem'

export interface PathCleanFiltersTableProps {
    filters?: PathCleaningFilter[]
    setFilters: (filters: PathCleaningFilter[]) => void
}

interface SortableRowProps {
    filter: PathCleaningFilter
    index: number
    onEdit: (filter: PathCleaningFilter) => void
    onRemove: () => void
}

function SortableRow({ filter, index, onEdit, onRemove }: SortableRowProps): JSX.Element {
    const [isModalVisible, setIsModalVisible] = useState(false)
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: `filter-${index}`,
    })

    const regex = filter.regex ?? ''
    const isInvalidRegex = !isValidRegexp(regex)

    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : 1,
    }

    return (
        <>
            {isModalVisible && (
                <PathRegexModal
                    filter={filter}
                    isOpen={isModalVisible}
                    onClose={() => setIsModalVisible(false)}
                    onSave={(updatedFilter: PathCleaningFilter) => {
                        onEdit(updatedFilter)
                        setIsModalVisible(false)
                    }}
                />
            )}
            <tr
                ref={setNodeRef}
                style={style}
                className={clsx('border-b border-border hover:bg-accent-light cursor-pointer', {
                    'border-warning': isInvalidRegex,
                })}
            >
                <td className="p-2 w-8">
                    <div className="flex items-center justify-center">
                        <IconSort
                            className="text-muted-alt cursor-grab active:cursor-grabbing"
                            {...attributes}
                            {...listeners}
                        />
                    </div>
                </td>
                <td className="p-2 w-12 text-center text-muted font-medium">{index + 1}</td>
                <td className="p-2">
                    <Tooltip title={isInvalidRegex ? 'Invalid regex pattern' : null}>
                        <code
                            className={clsx('font-mono text-sm px-2 py-1 rounded bg-accent-light', {
                                'text-danger border border-danger': isInvalidRegex,
                            })}
                        >
                            {regex || '(Empty)'}
                        </code>
                    </Tooltip>
                </td>
                <td className="p-2">
                    <div className="font-mono text-sm">{parseAliasToReadable(filter.alias || '(Empty)')}</div>
                </td>
                <td className="p-2 w-24">
                    <div className="flex items-center gap-1">
                        <LemonButton
                            icon={<IconPencil />}
                            size="xsmall"
                            onClick={() => setIsModalVisible(true)}
                            tooltip="Edit rule"
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            size="xsmall"
                            status="danger"
                            onClick={onRemove}
                            tooltip="Delete rule"
                        />
                    </div>
                </td>
            </tr>
        </>
    )
}

export function PathCleanFiltersTable({ filters = [], setFilters }: PathCleanFiltersTableProps): JSX.Element {
    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: {
                distance: 8,
            },
        }),
        useSensor(KeyboardSensor, {
            coordinateGetter: sortableKeyboardCoordinates,
        })
    )

    const onEditFilter = (index: number, filter: PathCleaningFilter): void => {
        const newFilters = filters.map((f, i) => (i === index ? filter : f))
        setFilters(newFilters)
    }

    const onRemoveFilter = (index: number): void => {
        setFilters(filters.filter((_, i) => i !== index))
    }

    const handleDragEnd = (event: any): void => {
        const { active, over } = event

        if (active.id !== over.id) {
            const oldIndex = filters.findIndex((_, index) => `filter-${index}` === active.id)
            const newIndex = filters.findIndex((_, index) => `filter-${index}` === over.id)

            setFilters(arrayMove(filters, oldIndex, newIndex))
        }
    }

    if (filters.length === 0) {
        return (
            <div className="text-center py-8 text-muted">
                No path cleaning rules configured. Add your first rule to get started.
            </div>
        )
    }

    return (
        <div className="border border-border rounded-lg overflow-hidden">
            <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={handleDragEnd}
                modifiers={[restrictToVerticalAxis]}
            >
                <table className="w-full">
                    <thead className="bg-accent-light">
                        <tr>
                            <th className="p-3 w-8" />
                            <th className="p-3 w-12 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                Order
                            </th>
                            <th className="p-3 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                Regex Pattern
                            </th>
                            <th className="p-3 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                Alias
                            </th>
                            <th className="p-3 w-24 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                Actions
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        <SortableContext
                            items={filters.map((_, index) => `filter-${index}`)}
                            strategy={verticalListSortingStrategy}
                        >
                            {filters.map((filter, index) => (
                                <SortableRow
                                    key={`filter-${index}`}
                                    filter={filter}
                                    index={index}
                                    onEdit={(updatedFilter) => onEditFilter(index, updatedFilter)}
                                    onRemove={() => onRemoveFilter(index)}
                                />
                            ))}
                        </SortableContext>
                    </tbody>
                </table>
            </DndContext>
        </div>
    )
}
