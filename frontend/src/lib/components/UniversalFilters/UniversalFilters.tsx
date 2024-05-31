import { IconChevronDown, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown, Popover } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { ActionFilter, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { PropertyFilterButton } from '../PropertyFilters/components/PropertyFilterButton'
import { TaxonomicPropertyFilter } from '../PropertyFilters/components/TaxonomicPropertyFilter'
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

export function UniversalFilters({
    pageKey = 'rootKey',
    group = null,
    allowGroups = false,
    allowFilters = false,
    onChange = (group: UniversalFilterGroup) => console.log(group),
}: {
    pageKey: string
    group: UniversalGroupFilter | UniversalGroupFilterValue | null
    allowGroups: boolean
    allowFilters: boolean
    onChange: (group: UniversalFilterGroup) => void
}): JSX.Element {
    console.log(pageKey)
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
                            onChange={(group: UniversalFilterGroup) => {
                                replaceGroupValue(index, group)
                            }}
                            allowGroups={false} // only ever allow a single level of group nesting
                            allowFilters={true}
                        />
                    </div>
                ) : (
                    <UniversalFilterRow
                        key={index}
                        pageKey={`${pageKey}.filter_${index}`}
                        filter={filterOrGroup}
                        index={index}
                        onRemove={() => removeGroupValue(index)}
                        onChange={() => {
                            console.log('TODO: implement update')
                        }}
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
                                TaxonomicFilterGroupType.Events,
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.Actions,
                                TaxonomicFilterGroupType.Cohorts,
                                TaxonomicFilterGroupType.SessionProperties,
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
    index,
    pageKey,
    onChange,
    onRemove,
}: {
    filter: AnyPropertyFilter | ActionFilter
    index: number
    pageKey: string
    onChange: (index: number, property: AnyPropertyFilter | ActionFilter) => void
    onRemove: (index: number) => void
}): JSX.Element => {
    const [open, setOpen] = useState<boolean>(false)

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible && isValidPropertyFilter(filter) && !filter.key) {
            onRemove(index)
        }
        setOpen(visible)
    }

    const isPropertyFilter = isValidPropertyFilter(filter)

    return (
        <Popover
            visible={open}
            onClickOutside={() => handleVisibleChange(false)}
            overlay={
                isPropertyFilter ? (
                    <TaxonomicPropertyFilter
                        key={index}
                        pageKey={pageKey}
                        index={index}
                        onComplete={() => setOpen(false)}
                        disablePopover={false}
                        filters={[]}
                        setFilter={onChange}
                    />
                ) : (
                    <div>Edit action</div>
                )
            }
        >
            {isPropertyFilter ? (
                <PropertyFilterButton onClick={() => setOpen(!open)} onClose={() => onRemove(index)} item={filter} />
            ) : (
                <div>Action filter</div>
            )}
        </Popover>
    )
}
