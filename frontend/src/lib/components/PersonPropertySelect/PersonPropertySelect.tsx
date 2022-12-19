import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Popup } from 'lib/components/Popup/Popup'
import { SortableContainer, SortableElement } from 'react-sortable-hoc'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlus } from '../icons'
import { LemonSnack } from '../LemonSnack/LemonSnack'
import clsx from 'clsx'
import { useState } from 'react'

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
    <span className={clsx(sortable ? 'cursor-move' : 'cursor-auto')}>
        <LemonSnack onClose={() => onRemove(name)}>{name}</LemonSnack>
    </span>
)

const SortableProperty = SortableElement(PropertyTag)

const SortablePropertyList = SortableContainer(({ children }: { children: React.ReactNode }) => {
    return <span className="flex items-center gap-2">{children}</span>
})

export const PersonPropertySelect = ({
    onChange,
    selectedProperties,
    addText,
    sortable = false,
}: PersonPropertySelectProps): JSX.Element => {
    const [open, setOpen] = useState<boolean>(false)

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
            {sortable ? (
                <SortablePropertyList onSortEnd={handleSort} axis="x" lockAxis="x" lockToContainerEdges distance={5}>
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
                <LemonButton onClick={() => setOpen(!open)} type="secondary" size="small" icon={<IconPlus />}>
                    {addText}
                </LemonButton>
            </Popup>
        </div>
    )
}
