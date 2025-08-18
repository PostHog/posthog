import { DndContext, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement } from '@dnd-kit/modifiers'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

export interface PropertySelectProps {
    addText: string
    onChange: (names: string[]) => void
    selectedProperties: string[]
    sortable?: boolean
    taxonomicFilterGroup: TaxonomicFilterGroupType.PersonProperties | TaxonomicFilterGroupType.EventProperties
}

const SortableProperty = ({
    name,
    onRemove,
    sortable,
}: {
    name: string
    onRemove: (val: string) => void
    sortable?: boolean
}): JSX.Element => {
    const { setNodeRef, attributes, transform, transition, listeners } = useSortable({ id: name })

    return (
        <span
            ref={setNodeRef}
            className={clsx(sortable ? 'cursor-move' : 'cursor-auto')}
            {...attributes}
            {...listeners}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <LemonSnack onClose={() => onRemove(name)}>{name}</LemonSnack>
        </span>
    )
}

export const PropertySelect = ({
    onChange,
    selectedProperties,
    addText,
    sortable = false,
    taxonomicFilterGroup,
}: PropertySelectProps): JSX.Element => {
    const [open, setOpen] = useState<boolean>(false)
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 1 } }))

    const handleChange = (name: string): void => {
        onChange(Array.from(new Set(selectedProperties.concat([name]))))
    }

    const handleRemove = (name: string): void => {
        onChange(selectedProperties.filter((p) => p !== name))
    }

    const handleSort = ({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void => {
        const newSelectedProperties = [...selectedProperties]
        const [removed] = newSelectedProperties.splice(oldIndex, 1)
        newSelectedProperties.splice(newIndex, 0, removed)
        onChange(newSelectedProperties)
    }

    return (
        <div className="flex flex-col gap-2">
            {selectedProperties.length > 0 && (
                <DndContext
                    onDragEnd={({ active, over }) => {
                        if (over && active.id !== over.id) {
                            handleSort({
                                oldIndex: selectedProperties.indexOf(active.id.toString()),
                                newIndex: selectedProperties.indexOf(over.id.toString()),
                            })
                        }
                    }}
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    modifiers={[restrictToParentElement]}
                >
                    <SortableContext
                        disabled={!sortable}
                        items={selectedProperties}
                        strategy={horizontalListSortingStrategy}
                    >
                        <div className="flex items-center gap-2 flex-wrap">
                            {selectedProperties.map((value) => (
                                <SortableProperty
                                    key={`item-${value}`}
                                    name={value}
                                    onRemove={handleRemove}
                                    sortable={sortable}
                                />
                            ))}
                        </div>
                    </SortableContext>
                </DndContext>
            )}

            <div>
                <Popover
                    visible={open}
                    onClickOutside={() => setOpen(false)}
                    overlay={
                        <TaxonomicFilter
                            onChange={(_, value) => {
                                handleChange(value as string)
                                setOpen(false)
                            }}
                            taxonomicGroupTypes={[taxonomicFilterGroup]}
                        />
                    }
                >
                    <LemonButton
                        onClick={() => setOpen(!open)}
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        sideIcon={null}
                    >
                        {addText}
                    </LemonButton>
                </Popover>
            </div>
        </div>
    )
}
