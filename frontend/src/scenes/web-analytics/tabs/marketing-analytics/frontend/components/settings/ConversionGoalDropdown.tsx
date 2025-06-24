import { useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { uuid } from 'lib/utils'
import { useState } from 'react'
import { LocalFilter } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'

import { actionsModel } from '~/models/actionsModel'
import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { conversionGoalPopoverFields } from '~/taxonomy/taxonomy'
import { ActionFilter, EntityType, EntityTypes } from '~/types'

import { ConversionGoalSchema, UTM_CAMPAIGN_NAME_SCHEMA_FIELD, UTM_SOURCE_NAME_SCHEMA_FIELD } from '../../../utils'
import { defaultConversionGoalFilter } from './constants'

export function taxonomicFilterGroupTypeToEntityType(
    taxonomicFilterGroupType: TaxonomicFilterGroupType
): EntityType | null {
    switch (taxonomicFilterGroupType) {
        case TaxonomicFilterGroupType.Events:
        case TaxonomicFilterGroupType.CustomEvents:
            return EntityTypes.EVENTS
        // TODO: in the future we will allow actions to be selected as conversion goals
        // case TaxonomicFilterGroupType.Actions:
        //     return EntityTypes.ACTIONS
        case TaxonomicFilterGroupType.DataWarehouse:
            return EntityTypes.DATA_WAREHOUSE
        default:
            return null
    }
}

const getValue = (
    value: string | number | null | undefined,
    filter: ActionFilter
): string | number | null | undefined => {
    if (filter.type === 'actions') {
        return typeof value === 'string' ? parseInt(value) : value || undefined
    }
    return value === null ? null : value || undefined
}

interface ConversionGoalDropdownProps {
    groupTypes?: TaxonomicFilterGroupType[]
    placeholder?: string
    value?: ConversionGoalFilter
    onChange?: (filter: ConversionGoalFilter, uuid?: string) => void
}

export function ConversionGoalDropdown({
    groupTypes = [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.CustomEvents,
        TaxonomicFilterGroupType.DataWarehouse,
    ],
    placeholder = 'Select event, custom event or any data warehouse table',
    value,
    onChange,
}: ConversionGoalDropdownProps): JSX.Element {
    const { actions } = useValues(actionsModel)

    const [internalFilter, setInternalFilter] = useState<ConversionGoalFilter>(defaultConversionGoalFilter)

    // Use controlled value if provided, otherwise use internal state
    const filter = value || internalFilter

    let name: string | null | undefined, filterValue: string | number | null | undefined

    if (filter.type === EntityTypes.ACTIONS) {
        const action = actions.find((action) => action.id === filter.id)
        name = action?.name || filter.name
        filterValue = action?.id || filter.id
    } else {
        name = filter.name || (filter.id !== null ? String(filter.id) : null)
        filterValue = filter.name || filter.id
    }

    // Create a local filter that matches TaxonomicPopover expectations
    const localFilter: LocalFilter = {
        ...filter,
        order: 0,
        uuid: uuid(),
    }

    const handleFilterChange = (updatedFilter: ConversionGoalFilter, filterUuid?: string): void => {
        if (onChange) {
            onChange(updatedFilter, filterUuid)
        } else {
            setInternalFilter(updatedFilter)
        }
    }

    return (
        <TaxonomicPopover
            fullWidth
            groupType={filter.type as TaxonomicFilterGroupType}
            value={getValue(filterValue, filter)}
            filter={localFilter}
            onChange={(changedValue, taxonomicGroupType, item) => {
                const groupType = taxonomicFilterGroupTypeToEntityType(taxonomicGroupType)

                if (groupType) {
                    const updatedFilter: ConversionGoalFilter = {
                        ...filter,
                        type: groupType,
                        id: changedValue ? changedValue : null,
                        name: item?.name ?? '',
                        schema: {
                            utm_campaign_name: 'utm_campaign',
                            utm_source_name: 'utm_source',
                        },
                    }
                    // If the group type is a data warehouse, we override the schema with the data warehouse schema
                    if (groupType === EntityTypes.DATA_WAREHOUSE) {
                        const overrideSchema: Record<ConversionGoalSchema, string> = {
                            utm_campaign_name: item[UTM_CAMPAIGN_NAME_SCHEMA_FIELD],
                            utm_source_name: item[UTM_SOURCE_NAME_SCHEMA_FIELD],
                        }
                        updatedFilter.schema = overrideSchema
                    }
                    handleFilterChange(updatedFilter, localFilter.uuid)
                }
            }}
            renderValue={() => (
                <span className="text-overflow max-w-full">
                    <EntityFilterInfo filter={localFilter} />
                </span>
            )}
            groupTypes={groupTypes}
            placeholder={placeholder}
            dataWarehousePopoverFields={conversionGoalPopoverFields}
            eventNames={name ? [name] : []}
        />
    )
}
