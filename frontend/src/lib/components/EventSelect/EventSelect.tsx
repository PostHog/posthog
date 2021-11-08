import React from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Tag } from 'antd'
import { Popup } from 'lib/components/Popup/Popup'

interface EventSelectProps {
    onChange: (names: string[]) => void
    selectedEvents: string[]
    addElement: JSX.Element
}

export const EventSelect = ({ onChange, selectedEvents, addElement }: EventSelectProps): JSX.Element => {
    const { open, toggle, hide } = usePopup()

    const handleChange = (name: string): void => {
        onChange(Array.from(new Set(selectedEvents.concat([name]))))
    }

    const handleRemove = (name: string): void => {
        onChange(selectedEvents.filter((p) => p !== name))
    }

    // Add in the toggle popup logic for the passed in element
    const addElementWithToggle = React.cloneElement(addElement, { onClick: toggle })

    return (
        <div style={{ marginBottom: 16 }}>
            {selectedEvents.map((name) => (
                <PropertyTag handleRemove={handleRemove} name={name} key={name} />
            ))}

            <Popup
                visible={open}
                onClickOutside={() => hide()}
                overlay={
                    <TaxonomicFilter
                        onChange={(_, value) => {
                            handleChange(value as string)
                            hide()
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

const popupLogic = {
    // eslint-disable-next-line @typescript-eslint/explicit-function-return-type
    toggle: (open: boolean) => !open,

    // eslint-disable-next-line @typescript-eslint/explicit-function-return-type
    hide: () => false,
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
const usePopup = () => {
    const [open, setOpen] = React.useState<boolean>(false)

    return {
        open,
        toggle: () => setOpen(popupLogic.toggle(open)),
        hide: () => setOpen(popupLogic.hide()),
    }
}

type PropertyTagProps = {
    name: string
    handleRemove: (name: string) => void
}

const PropertyTag = ({ name, handleRemove }: PropertyTagProps): JSX.Element => (
    <Tag
        key={name}
        closable
        onClose={(): void => handleRemove(name)}
        style={{
            margin: '0.25rem',
            padding: '0.25rem 0.5em',
            background: '#D9D9D9',
            border: '1px solid #D9D9D9',
            borderRadius: '40px',
            fontSize: 'inherit',
        }}
    >
        {name}
    </Tag>
)
