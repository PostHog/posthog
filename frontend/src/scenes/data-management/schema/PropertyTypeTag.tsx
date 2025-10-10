import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType } from '~/types'

import { PropertyType } from './schemaManagementLogic'

interface PropertyTypeTagProps {
    propertyName: string
    schemaPropertyType: PropertyType
}

export function PropertyTypeTag({ propertyName, schemaPropertyType }: PropertyTypeTagProps): JSX.Element {
    const { getPropertyDefinition } = useValues(propertyDefinitionsModel)
    const propertyDefinition = getPropertyDefinition(propertyName, PropertyDefinitionType.Event)

    const hasTypeMismatch =
        propertyDefinition &&
        propertyDefinition.property_type &&
        propertyDefinition.property_type !== schemaPropertyType

    return (
        <div className="flex items-center gap-1">
            <LemonTag type="muted">{schemaPropertyType}</LemonTag>
            {hasTypeMismatch && (
                <Tooltip
                    title={`Type mismatch: Property management defines this as ${propertyDefinition.property_type}`}
                >
                    <IconWarning className="text-warning text-base" />
                </Tooltip>
            )}
        </div>
    )
}
