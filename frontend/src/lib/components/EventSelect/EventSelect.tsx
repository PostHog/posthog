import React, { useState } from 'react'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

interface EventSelectProps {
    onItemChange?: (values: any[]) => void
    onChange?: (names: string[]) => void
    selectedEvents: string[]
    selectedItems?: any[]
    addElement: JSX.Element
    filterGroupTypes?: TaxonomicFilterGroupType[]
    /** Allow users to select events that haven't been captured yet (default: false) */
    allowNonCapturedEvents?: boolean
}

export const EventSelect = ({
    onItemChange,
    onChange,
    selectedEvents,
    selectedItems,
    addElement,
    filterGroupTypes,
    allowNonCapturedEvents = false,
}: EventSelectProps): JSX.Element => {
    const [open, setOpen] = useState<boolean>(false)
    const eventSelectFilterGroupTypes = filterGroupTypes || [TaxonomicFilterGroupType.Events]

    const handleChange = (name: string): void => {
        if (onChange) {
            onChange(Array.from(new Set(selectedEvents.concat([name]))))
        }
    }

    const handleItemChange = (item: any): void => {
        if (selectedItems && onItemChange) {
            onItemChange(Array.from(new Set(selectedItems?.concat([item]))))
        }
    }

    const handleRemove = (name: string): void => {
        if (onChange) {
            onChange(selectedEvents.filter((p) => p !== name))
        }
        if (onItemChange && selectedItems) {
            onItemChange(selectedItems?.filter((p) => p.name !== name))
        }
    }

    // Check if an event is non-captured (not captured yet)
    const isNonCapturedEvent = (eventName: string): boolean => {
        return selectedItems?.some((item) => item.name === eventName && item.isNonCaptured) || false
    }

    // Add in the toggle popover logic for the passed in element
    const addElementWithToggle = React.cloneElement(addElement, { onClick: () => setOpen(!open) })

    return (
        <div className="flex items-center flex-wrap gap-2">
            {selectedEvents.map((name) => (
                <LemonSnack key={name} onClose={() => handleRemove(name)}>
                    <div className="flex items-center gap-1">
                        <span>{name}</span>
                        {isNonCapturedEvent(name) && (
                            <LemonTag type="warning" size="small">
                                Not captured yet
                            </LemonTag>
                        )}
                    </div>
                </LemonSnack>
            ))}

            <Popover
                visible={open}
                onClickOutside={() => setOpen(false)}
                overlay={
                    <TaxonomicFilter
                        onChange={(_, value, item) => {
                            handleItemChange(item)
                            handleChange(value as string)
                            setOpen(false)
                        }}
                        taxonomicGroupTypes={eventSelectFilterGroupTypes}
                        allowNonCapturedEvents={allowNonCapturedEvents}
                    />
                }
            >
                {addElementWithToggle}
            </Popover>
        </div>
    )
}
