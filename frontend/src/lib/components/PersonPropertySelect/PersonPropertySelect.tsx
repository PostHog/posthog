import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlus } from 'lib/lemon-ui/icons'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import clsx from 'clsx'
import { useState } from 'react'

import { DndContext, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { useSortable, SortableContext, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { restrictToHorizontalAxis, restrictToParentElement } from '@dnd-kit/modifiers'

export interface PersonPropertySelectProps {
    addText: string
    onChange: (names: string[]) => void
    selectedProperties: string[]
    sortable?: boolean
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
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <LemonSnack onClose={() => onRemove(name)}>{name}</LemonSnack>
        </span>
    )
}

export const PersonPropertySelect = ({
    onChange,
    selectedProperties,
    addText,
    sortable = false,
}: PersonPropertySelectProps): JSX.Element => {
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
        <div className="flex items-center flex-wrap gap-2">
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
                    modifiers={[restrictToHorizontalAxis, restrictToParentElement]}
                >
                    <SortableContext
                        disabled={!sortable}
                        items={selectedProperties}
                        strategy={horizontalListSortingStrategy}
                    >
                        <div className="flex items-center gap-2">
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

            <Popover
                visible={open}
                onClickOutside={() => setOpen(false)}
                overlay={
                    <TaxonomicFilter
                        onChange={(_, value) => {
                            handleChange(value as string)
                            setOpen(false)
                        }}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
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
    )
}
