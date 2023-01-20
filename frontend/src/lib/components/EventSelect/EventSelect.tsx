import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Popup } from 'lib/components/Popup/Popup'
import { LemonSnack } from '../LemonSnack/LemonSnack'
import React, { useState } from 'react'

interface EventSelectProps {
    onChange: (names: string[]) => void
    selectedEvents: string[]
    addElement: JSX.Element
}

export const EventSelect = ({ onChange, selectedEvents, addElement }: EventSelectProps): JSX.Element => {
    const [open, setOpen] = useState<boolean>(false)

    const handleChange = (name: string): void => {
        onChange(Array.from(new Set(selectedEvents.concat([name]))))
    }

    const handleRemove = (name: string): void => {
        onChange(selectedEvents.filter((p) => p !== name))
    }

    // Add in the toggle popup logic for the passed in element
    const addElementWithToggle = React.cloneElement(addElement, { onClick: () => setOpen(!open) })

    return (
        <div className="flex items-center flex-wrap gap-2">
            {selectedEvents.map((name) => (
                <LemonSnack key={name} onClose={() => handleRemove(name)}>
                    {name}
                </LemonSnack>
            ))}

            <Popup
                visible={open}
                onClickOutside={() => setOpen(false)}
                overlay={
                    <TaxonomicFilter
                        onChange={(_, value) => {
                            handleChange(value as string)
                            setOpen(false)
                        }}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    />
                }
            >
                {addElementWithToggle}
            </Popup>
        </div>
    )
}
