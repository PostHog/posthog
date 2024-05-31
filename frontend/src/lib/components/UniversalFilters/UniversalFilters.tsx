import { IconChevronDown, IconFilter, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown, Popover } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { getEventNamesForAction } from 'lib/utils'
import { useState } from 'react'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { ActionFilter, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { EntityFilterInfo } from '../EntityFilterInfo'
import { PropertyFilterButton } from '../PropertyFilters/components/PropertyFilterButton'
import { TaxonomicPropertyFilter } from '../PropertyFilters/components/TaxonomicPropertyFilter'
import { PropertyFilters } from '../PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from '../PropertyFilters/utils'
import { TaxonomicFilter } from '../TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { universalFiltersLogic } from './universalFiltersLogic'
import { isUniversalGroupFilterLike } from './utils'

export interface UniversalGroupFilter {
    type: FilterLogicalOperator
    values: UniversalGroupFilterValue[]
}

export interface UniversalGroupFilterValue {
    type: FilterLogicalOperator
    values: UniversalFilterValue[]
}

export type UniversalFilterValue = AnyPropertyFilter | ActionFilter
export type UniversalFilterGroup = UniversalGroupFilter | UniversalGroupFilterValue

type UniversalFiltersProps = {
    pageKey: string
    group: UniversalGroupFilter | UniversalGroupFilterValue | null
    allowGroups: boolean
    allowFilters: boolean
    onChange: (group: UniversalFilterGroup) => void
    taxonomicEntityFilterGroupTypes: TaxonomicFilterGroupType[]
    taxonomicPropertyFilterGroupTypes: TaxonomicFilterGroupType[]
}

export function UniversalFilters({
    pageKey = 'rootKey',
    group = null,
    allowGroups = false,
    allowFilters = false,
    onChange = (group: UniversalFilterGroup) => console.log(group),
    taxonomicEntityFilterGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    taxonomicPropertyFilterGroupTypes = [
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.SessionProperties,
    ],
}: UniversalFiltersProps): JSX.Element {
    const logic = universalFiltersLogic({ pageKey, group, onChange })
    const { filterGroup } = useValues(logic)
    const { addFilterGroup, replaceGroupValue, removeGroupValue, addGroupFilter } = useActions(logic)
    const [dropdownOpen, setDropdownOpen] = useState<boolean>(false)
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)

    return (
        <div>
            <div>Root Type: {filterGroup.type}</div>
            <div>Values: {JSON.stringify(filterGroup.values)}</div>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <div className="border">
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
                    </div>
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
        </div>
    )
}

const UniversalFilterRow = ({
    filter,
    pageKey,
    onChange,
    onRemove,
    taxonomicPropertyFilterGroupTypes,
}: {
    filter: AnyPropertyFilter | ActionFilter
    pageKey: string
    onChange: (property: AnyPropertyFilter | ActionFilter) => void
    onRemove: () => void
    taxonomicPropertyFilterGroupTypes: UniversalFiltersProps['taxonomicPropertyFilterGroupTypes']
}): JSX.Element => {
    const { actions } = useValues(actionsModel)
    const [open, setOpen] = useState<boolean>(false)

    const isPropertyFilter = isValidPropertyFilter(filter) // TODO: maybe won't be valid initially

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            overlay={
                isPropertyFilter ? (
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
                ) : (
                    <PropertyFilters
                        pageKey={pageKey}
                        propertyFilters={filter.properties}
                        onChange={(properties) => onChange({ ...filter, properties })}
                        disablePopover={true}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                        eventNames={
                            filter.type === TaxonomicFilterGroupType.Events && filter.id
                                ? [String(filter.id)]
                                : filter.type === TaxonomicFilterGroupType.Actions && filter.id
                                ? getEventNamesForAction(parseInt(String(filter.id)), actions)
                                : []
                        }
                    />
                )
            }
        >
            <PropertyFilterButton
                onClick={isPropertyFilter ? () => setOpen(!open) : undefined}
                onClose={() => onRemove()}
                item={filter}
            >
                {isPropertyFilter ? null : (
                    <div className="flex items-center space-x-1">
                        <EntityFilterInfo filter={filter} />
                        <LemonButton
                            size="xsmall"
                            icon={
                                <IconWithCount count={filter.properties?.length || 0} showZero={false}>
                                    <IconFilter />
                                </IconWithCount>
                            }
                            className="p-0.5"
                            onClick={() => setOpen(!open)}
                        />
                    </div>
                )}
            </PropertyFilterButton>
        </Popover>
    )
}
