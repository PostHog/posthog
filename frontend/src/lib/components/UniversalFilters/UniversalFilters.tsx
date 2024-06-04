import { IconChevronDown, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown, Popover } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { getEventNamesForAction } from 'lib/utils'
import { useState } from 'react'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { ActionFilter, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { TaxonomicPropertyFilter } from '../PropertyFilters/components/TaxonomicPropertyFilter'
import { PropertyFilters } from '../PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from '../PropertyFilters/utils'
import { TaxonomicFilter } from '../TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { UniversalFilterButton } from './UniversalFilterButton'
import { universalFiltersLogic } from './universalFiltersLogic'
import { isActionFilter, isUniversalGroupFilterLike } from './utils'

export interface UniversalFiltersGroup {
    type: FilterLogicalOperator
    values: UniversalFiltersGroupValue[]
}

export type UniversalFiltersGroupValue = UniversalFiltersGroup | UniversalFilterValue
export type UniversalFilterValue = AnyPropertyFilter | ActionFilter

type UniversalFiltersProps = {
    pageKey: string
    group: UniversalFiltersGroup | null
    onChange: (group: UniversalFiltersGroup) => void
    taxonomicEntityFilterGroupTypes: TaxonomicFilterGroupType[]
    taxonomicPropertyFilterGroupTypes: TaxonomicFilterGroupType[]
    allowGroups?: boolean
    allowFilters?: boolean
}

export function UniversalFilters({
    pageKey = 'rootKey',
    group = null,
    allowGroups = false,
    allowFilters = false,
    onChange,
    taxonomicEntityFilterGroupTypes,
    taxonomicPropertyFilterGroupTypes,
}: UniversalFiltersProps): JSX.Element {
    const [dropdownOpen, setDropdownOpen] = useState<boolean>(false)

    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)

    const logic = universalFiltersLogic({ pageKey, group, onChange })
    const { filterGroup } = useValues(logic)
    const { addFilterGroup, replaceGroupValue, removeGroupValue, addGroupFilter } = useActions(logic)

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters
                        key={index}
                        pageKey={`${pageKey}.group_${index}`}
                        group={filterOrGroup}
                        onChange={(group) => replaceGroupValue(index, group)}
                        allowGroups={false} // only ever allow a single level of group nesting
                        allowFilters={true}
                        taxonomicEntityFilterGroupTypes={taxonomicEntityFilterGroupTypes}
                        taxonomicPropertyFilterGroupTypes={taxonomicPropertyFilterGroupTypes}
                    />
                ) : (
                    <UniversalFilterRow
                        key={index}
                        pageKey={`${pageKey}.filter_${index}`}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        taxonomicPropertyFilterGroupTypes={taxonomicPropertyFilterGroupTypes}
                    />
                )
            })}

            {allowFilters && (
                <LemonDropdown
                    overlay={
                        <TaxonomicFilter
                            onChange={(taxonomicGroup, value, item) => {
                                addGroupFilter(taxonomicGroup, value, item)
                                setDropdownOpen(false)
                            }}
                            taxonomicGroupTypes={[
                                ...taxonomicEntityFilterGroupTypes,
                                ...taxonomicPropertyFilterGroupTypes,
                            ]}
                        />
                    }
                    visible={dropdownOpen}
                    onClickOutside={() => setDropdownOpen(false)}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlusSmall />}
                        sideIcon={null}
                        sideAction={
                            allowGroups
                                ? {
                                      icon: <IconChevronDown />,
                                      dropdown: {
                                          overlay: (
                                              <LemonButton fullWidth onClick={addFilterGroup}>
                                                  Add filter group
                                              </LemonButton>
                                          ),
                                      },
                                  }
                                : null
                        }
                        onClick={() => setDropdownOpen(!dropdownOpen)}
                    >
                        Add filter
                    </LemonButton>
                </LemonDropdown>
            )}
        </>
    )
}

const UniversalFilterRow = ({
    filter,
    pageKey,
    onChange,
    onRemove,
    taxonomicPropertyFilterGroupTypes,
}: {
    filter: UniversalFilterValue
    pageKey: string
    onChange: (property: UniversalFilterValue) => void
    onRemove: () => void
    taxonomicPropertyFilterGroupTypes: UniversalFiltersProps['taxonomicPropertyFilterGroupTypes']
}): JSX.Element => {
    const isEntity = isActionFilter(filter)

    const { actions } = useValues(actionsModel)
    const [open, setOpen] = useState<boolean>(!isEntity)

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            overlay={
                isEntity ? (
                    <PropertyFilters
                        pageKey={pageKey}
                        propertyFilters={filter.properties}
                        onChange={(properties) => onChange({ ...filter, properties })}
                        disablePopover
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                        eventNames={
                            filter.type === TaxonomicFilterGroupType.Events && filter.id
                                ? [String(filter.id)]
                                : filter.type === TaxonomicFilterGroupType.Actions && filter.id
                                ? getEventNamesForAction(parseInt(String(filter.id)), actions)
                                : []
                        }
                    />
                ) : (
                    <TaxonomicPropertyFilter
                        pageKey={pageKey}
                        index={0}
                        filters={[filter]}
                        onComplete={() => {
                            if (isValidPropertyFilter(filter) && !filter.key) {
                                onRemove()
                            }
                        }}
                        setFilter={(_, property) => onChange(property)}
                        disablePopover={false}
                        taxonomicGroupTypes={taxonomicPropertyFilterGroupTypes}
                    />
                )
            }
        >
            <UniversalFilterButton onClick={() => setOpen(!open)} onClose={onRemove} filter={filter} />
        </Popover>
    )
}
