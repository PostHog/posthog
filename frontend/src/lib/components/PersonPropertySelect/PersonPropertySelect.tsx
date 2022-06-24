import React from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Button, Tag } from 'antd'
import { Popup } from 'lib/components/Popup/Popup'
import PlusCircleOutlined from '@ant-design/icons/lib/icons/PlusCircleOutlined'
import { SortableContainer, SortableElement } from 'react-sortable-hoc'

interface PersonPropertySelectProps {
    addText: string
    onChange: (names: string[]) => void
    selectedProperties: string[]
    sortable?: boolean
}

const PropertyTag = ({
    name,
    onRemove,
    sortable = false,
}: {
    name: string
    onRemove: (val: string) => void
    sortable?: boolean
}): JSX.Element => (
    <span style={{ display: 'inline-block' }}>
        <Tag
            closable
            onClose={(): void => onRemove(name)}
            style={{
                display: 'inline-block',
                margin: '0.25rem',
                padding: '0.25rem 0.5em',
                background: '#D9D9D9',
                border: '1px solid #D9D9D9',
                borderRadius: '40px',
                fontSize: 'inherit',
                cursor: sortable ? 'move' : 'auto',
            }}
        >
            {name}
        </Tag>
    </span>
)

const SortableProperty = SortableElement(PropertyTag)

const SortablePropertyList = SortableContainer(({ children }: { children: React.ReactNode }) => {
    return <span>{children}</span>
})

export const PersonPropertySelect = ({
    onChange,
    selectedProperties,
    addText,
    sortable = false,
}: PersonPropertySelectProps): JSX.Element => {
    const { open, toggle, hide } = usePopup()

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
        <div style={{ marginBottom: 16 }}>
            {sortable ? (
                <SortablePropertyList onSortEnd={handleSort} axis="x" lockAxis="x" lockToContainerEdges>
                    {selectedProperties.map((value, index) => (
                        <SortableProperty
                            key={`item-${value}`}
                            index={index}
                            name={value}
                            onRemove={handleRemove}
                            sortable
                        />
                    ))}
                </SortablePropertyList>
            ) : (
                selectedProperties?.map((value) => (
                    <PropertyTag key={`item-${value}`} name={value} onRemove={handleRemove} />
                ))
            )}
            <Popup
                visible={open}
                onClickOutside={() => hide()}
                overlay={
                    <TaxonomicFilter
                        onChange={(_, value) => {
                            handleChange(value as string)
                            hide()
                        }}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                    />
                }
            >
                <Button onClick={() => toggle()} type="link" className="new-prop-filter" icon={<PlusCircleOutlined />}>
                    {addText}
                </Button>
            </Popup>
        </div>
    )
}

const popupLogic = {
    toggle: (open: boolean) => !open,
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
