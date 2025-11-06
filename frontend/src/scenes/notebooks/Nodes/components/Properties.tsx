import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonLabel } from '@posthog/lemon-ui'

import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

import { PropertyDefinitionType } from '~/types'

interface PropertiesProps {
    pinnedProperties: Record<string, string | number | boolean>
    unpinnedProperties: Record<string, string | number | boolean>
    onPin: (propertyName: string) => void
    onUnpin: (propertyName: string) => void
}

export function Properties({ pinnedProperties, unpinnedProperties, ...props }: PropertiesProps): JSX.Element | null {
    const numUnpinnedProperties = Object.keys(unpinnedProperties).length
    const numPinnedProperties = Object.keys(pinnedProperties).length

    return (
        <div className="py-2 px-4 text-xs">
            {Object.entries(pinnedProperties).map(([key, value], index) => {
                const isLast = index === numPinnedProperties + numUnpinnedProperties - 1

                return <PropertyItem key={key} name={key} value={value} isLast={isLast} isPinned {...props} />
            })}
            {Object.entries(unpinnedProperties).map(([key, value], index) => {
                const isLast = index === numUnpinnedProperties - 1

                return <PropertyItem key={key} name={key} value={value} isLast={isLast} {...props} />
            })}
        </div>
    )
}

interface PropertyItemProps {
    name: string
    value: any
    isLast: boolean
    isPinned?: boolean
    onPin: (propertyName: string) => void
    onUnpin: (propertyName: string) => void
}

function PropertyItem({ name, value, isLast, isPinned = false, onPin, onUnpin }: PropertyItemProps): JSX.Element {
    const Icon = isPinned ? IconPinFilled : IconPin
    const onClick = isPinned ? () => onUnpin(name) : () => onPin(name)

    return (
        <div key={name} className="mb-1">
            <LemonLabel className="flex justify-between leading-4">
                <PropertyKeyInfo value={name} />
                <LemonButton noPadding size="small" icon={<Icon />} onClick={onClick} />
            </LemonLabel>
            <div className={`${!isLast && 'border-b border-primary pb-1'}`}>
                <PropertiesTable properties={value} rootKey={name} type={PropertyDefinitionType.Person} />
            </div>
        </div>
    )
}
