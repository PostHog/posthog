import { DndContext, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement } from '@dnd-kit/modifiers'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button, Chip, ChipClose, Popover as QuillPopover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

export interface PropertySelectProps {
    addText: string
    onChange: (names: string[]) => void
    selectedProperties: string[]
    sortable?: boolean
    taxonomicFilterGroup: TaxonomicFilterGroupType.PersonProperties | TaxonomicFilterGroupType.EventProperties
    disabledReason?: string | null
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
    const quillSurface = useQuillSurface()

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
            {quillSurface ? (
                <Chip>
                    {name}
                    <ChipClose aria-label={`Remove ${name}`} onClick={() => onRemove(name)} />
                </Chip>
            ) : (
                <LemonSnack onClose={() => onRemove(name)}>{name}</LemonSnack>
            )}
        </span>
    )
}

export const PropertySelect = ({
    onChange,
    selectedProperties,
    addText,
    sortable = false,
    taxonomicFilterGroup,
    disabledReason,
}: PropertySelectProps): JSX.Element => {
    const [open, setOpen] = useState<boolean>(false)
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 1 } }))
    const quillSurface = useQuillSurface()

    const handleChange = (name: string): void => {
        onChange(Array.from(new Set(selectedProperties.concat([name]))))
    }

    const handleRemove = (name: string): void => {
        onChange(selectedProperties.filter((p) => p !== name))
    }

    const addProperty = (value: TaxonomicFilterValue): void => {
        handleChange(value as string)
        setOpen(false)
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

            {quillSurface ? (
                <div>
                    <QuillPopover
                        open={open}
                        onOpenChange={(next, details) => {
                            if (closesIntoLemonPopover(next, details)) {
                                details.cancel()
                                return
                            }
                            setOpen(next)
                        }}
                    >
                        <PopoverTrigger
                            render={
                                <Button variant="outline" disabledReason={disabledReason || undefined}>
                                    <IconPlus />
                                    {addText}
                                </Button>
                            }
                        />
                        <PopoverContent align="start" className="w-auto p-0">
                            {/* The filter is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                            <div data-not-quill>
                                <TaxonomicFilter
                                    onChange={(_, value) => addProperty(value)}
                                    taxonomicGroupTypes={[taxonomicFilterGroup]}
                                />
                            </div>
                        </PopoverContent>
                    </QuillPopover>
                </div>
            ) : (
                <div>
                    <Popover
                        visible={open}
                        onClickOutside={() => setOpen(false)}
                        overlay={
                            <TaxonomicFilter
                                onChange={(_, value) => addProperty(value)}
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
                            disabledReason={disabledReason}
                        >
                            {addText}
                        </LemonButton>
                    </Popover>
                </div>
            )}
        </div>
    )
}
