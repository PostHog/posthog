import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'

import { PropertyDefinitionType } from '~/types'

import { sortProperties } from '../utils'

interface PropertiesProps {
    properties: Record<string, any>
    pinnedProperties: string[]
    onPin: (propertyName: string) => void
    onUnpin: (propertyName: string) => void
    type: PropertyDefinitionType
}

export function Properties({
    properties,
    pinnedProperties,
    onPin,
    onUnpin,
    type,
}: PropertiesProps): JSX.Element | null {
    const [searchTerm, setSearchTerm] = useState('')
    const { hideNullValues } = useValues(userPreferencesLogic)
    const { setHideNullValues } = useActions(userPreferencesLogic)

    const filteredProperties = useMemo(() => {
        let entries = Object.entries(properties)

        if (searchTerm) {
            const normalizedSearchTerm = searchTerm.toLowerCase()
            entries = entries.filter(([key, value]) => {
                return (
                    key.toLowerCase().includes(normalizedSearchTerm) ||
                    JSON.stringify(value).toLowerCase().includes(normalizedSearchTerm)
                )
            })
        }

        if (hideNullValues) {
            entries = entries.filter(([, value]) => value !== null)
        }

        entries = sortProperties(entries, pinnedProperties)

        return Object.fromEntries(entries)
    }, [properties, searchTerm, hideNullValues, pinnedProperties])

    const numProperties = Object.keys(filteredProperties).length
    const totalProperties = Object.keys(properties).length

    return (
        <div className="py-2 px-4 text-xs">
            <div className="flex items-center gap-2 mb-2">
                <LemonInput
                    type="search"
                    placeholder="Search properties..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    size="small"
                    className="flex-1"
                />
                <LemonCheckbox
                    checked={!hideNullValues}
                    onChange={(checked) => setHideNullValues(!checked)}
                    label="Show null"
                    size="small"
                />
            </div>

            {numProperties === 0 ? (
                <div className="text-muted text-center py-2 text-xs">
                    {searchTerm || hideNullValues
                        ? `No properties match your filters (${totalProperties} total)`
                        : 'No properties'}
                </div>
            ) : (
                <div>
                    {Object.entries(filteredProperties).map(([key, value], index) => {
                        const isPinned = pinnedProperties.includes(key)
                        const Icon = isPinned ? IconPinFilled : IconPin
                        const onClick = isPinned ? () => onUnpin(key) : () => onPin(key)
                        const isLast = index === numProperties - 1

                        return (
                            <div key={key} className="mb-1">
                                <div className="flex justify-between leading-4">
                                    <PropertyKeyInfo value={key} />
                                    <LemonButton noPadding size="small" icon={<Icon />} onClick={onClick} />
                                </div>
                                <div className={`${!isLast && 'border-b border-primary pb-1'}`}>
                                    <PropertiesTable
                                        properties={value}
                                        rootKey={key}
                                        type={type}
                                        embedded
                                        sortProperties={false}
                                    />
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}

            {(searchTerm || hideNullValues) && numProperties > 0 && (
                <div className="text-muted text-xs mt-1">
                    Showing {numProperties} of {totalProperties} properties
                </div>
            )}
        </div>
    )
}
