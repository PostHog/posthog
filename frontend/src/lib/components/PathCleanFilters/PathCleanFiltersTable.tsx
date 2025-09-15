import {
    DndContext,
    DragEndEvent,
    KeyboardSensor,
    PointerSensor,
    closestCenter,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, arrayMove, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useEffect, useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { isValidRegexp } from 'lib/utils/regexp'

import { PathCleaningFilter } from '~/types'

import { parseAliasToReadable } from './PathCleanFilterItem'
import { PathRegexModal } from './PathRegexModal'
import { ensureFilterOrder, updateFilterOrder } from './pathCleaningUtils'

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
        transition: isDragging ? 'none' : transition,
        opacity: isDragging ? 0.8 : 1,
        zIndex: isDragging ? 1000 : 'auto',
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
                className={clsx('border-b border-border hover:bg-bg-light transition-colors duration-150 bg-bg-light', {
                    'border-warning': isInvalidRegex,
                    'bg-bg-3000': isDragging,
                    'shadow-lg': isDragging,
                })}
            >
                <td className="py-1 px-2 w-8">
                    <div
                        className="flex items-center justify-center cursor-grab active:cursor-grabbing"
                        {...attributes}
                        {...listeners}
                    >
                        <SortableDragIcon className="text-muted-alt h-3 w-3" />
                    </div>
                </td>
                <td className="py-1 px-2 w-12 text-center text-muted font-medium text-sm">{index + 1}</td>
                <td className="py-1 px-2">
                    <Tooltip title={isInvalidRegex ? 'Invalid regex pattern' : null}>
                        <code
                            className={clsx('font-mono text-xs px-1 py-0.5 rounded bg-accent-light text-accent', {
                                'text-danger border border-danger bg-danger-light': isInvalidRegex,
                            })}
                        >
                            {regex || '(Empty)'}
                        </code>
                    </Tooltip>
                </td>
                <td className="py-1 px-2">
                    <div className="font-mono text-xs">{parseAliasToReadable(filter.alias || '(Empty)')}</div>
                </td>
                <td className="py-1 px-2 w-20">
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
    const [localFilters, setLocalFilters] = useState(filters)
    const [isDragging, setIsDragging] = useState(false)

    // Sync local state with props, but not during drag to avoid flicker
    useEffect(() => {
        if (!isDragging) {
            setLocalFilters(ensureFilterOrder(filters))
        }
    }, [filters, isDragging])

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

    const updateFilters = (newFilters: PathCleaningFilter[]): void => {
        const filtersWithOrder = updateFilterOrder(newFilters)
        setLocalFilters(filtersWithOrder)
        setFilters(filtersWithOrder)
    }

    const onEditFilter = (index: number, filter: PathCleaningFilter): void => {
        const newFilters = localFilters.map((f, i) => (i === index ? filter : f))
        updateFilters(newFilters)
    }

    const onRemoveFilter = (index: number): void => {
        updateFilters(localFilters.filter((_, i) => i !== index))
    }

    const handleDragStart = (): void => {
        setIsDragging(true)
    }

    const handleDragEnd = (event: DragEndEvent): void => {
        setIsDragging(false)
        const { active, over } = event

        if (over && active.id !== over.id) {
            const oldIndex = localFilters.findIndex((_, index) => `filter-${index}` === active.id)
            const newIndex = localFilters.findIndex((_, index) => `filter-${index}` === over.id)

            if (oldIndex !== -1 && newIndex !== -1) {
                updateFilters(arrayMove(localFilters, oldIndex, newIndex))
            }
        }
    }

    if (localFilters.length === 0) {
        return (
            <div className="text-center py-8 text-muted">
                No path cleaning rules configured. Add your first rule to get started.
            </div>
        )
    }

    return (
        <div className="border border-border rounded-lg overflow-hidden bg-bg-light">
            <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
                modifiers={[restrictToVerticalAxis]}
            >
                <table className="w-full bg-bg-light">
                    <thead className="bg-bg-3000">
                        <tr>
                            <th className="py-2 px-2 w-8" />
                            <th className="py-2 px-2 w-12 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                Order
                            </th>
                            <th className="py-2 px-2 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                Regex Pattern
                            </th>
                            <th className="py-2 px-2 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                Alias
                            </th>
                            <th className="py-2 px-2 w-20 text-left text-xs font-semibold text-muted-alt uppercase tracking-wider">
                                Actions
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        <SortableContext
                            items={localFilters.map((_, index) => `filter-${index}`)}
                            strategy={verticalListSortingStrategy}
                        >
                            {localFilters.map((filter, index) => (
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
