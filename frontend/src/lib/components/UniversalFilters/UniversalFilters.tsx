import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { ActionFilter, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { PropertyFilterButton } from '../PropertyFilters/components/PropertyFilterButton'
import { TaxonomicPropertyFilter } from '../PropertyFilters/components/TaxonomicPropertyFilter'
import { isValidPropertyFilter } from '../PropertyFilters/utils'
import { universalFiltersLogic, UniversalFiltersLogicProps } from './universalFiltersLogic'
import { isUniversalGroupFilterLike } from './utils'

export interface UniversalGroupFilter {
    type: FilterLogicalOperator
    values: UniversalGroupFilterValue[]
}

export interface UniversalGroupFilterValue {
    type: FilterLogicalOperator
    values: (AnyPropertyFilter | ActionFilter | UniversalGroupFilterValue)[]
}

export function UniversalFilters({
    pageKey = 'rootKey',
    addText = 'Add filter group',
    filters = null,
    onAdd: _onAdd,
    onChange: _onChange = (_, property: AnyPropertyFilter | ActionFilter) => console.log(property),
    onRemove: _onRemove = (index: number) => console.log('remove', index),
}: {
    pageKey: string
    addText: string
    filters: UniversalFiltersLogicProps['filters']
    onAdd: () => void
    onChange: (index: number, property: AnyPropertyFilter | ActionFilter) => void
    onRemove: (index: number) => void
}): JSX.Element {
    const logic = universalFiltersLogic({ pageKey, filters })
    const { rootGroup } = useValues(logic)
    const { addFilterGroup, setInnerGroupFilters } = useActions(logic)

    const onAdd = _onAdd || addFilterGroup

    return (
        <div>
            <div>Root Type: {rootGroup.type}</div>
            {rootGroup.values.map((filterOrGroup, index) => {
                // ;<PropertyFilters
                //     addText="Add filter"
                //     propertyFilters={isPropertyGroupFilterLike(group) ? (group.values as AnyPropertyFilter[]) : null}
                //     onChange={(properties) => {
                //         setPropertyFilters(properties, propertyGroupIndex)
                //     }}
                //     pageKey={`${keyForInsightLogicProps('new')(
                //         insightProps
                //     )}-PropertyGroupFilters-${propertyGroupIndex}`}
                //     taxonomicGroupTypes={taxonomicGroupTypes}
                //     eventNames={eventNames}
                //     propertyGroupType={group.type}
                //     orFiltering
                // />
                const key = `${pageKey}.${index}`

                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <div className="border">
                        <div>Type: {filterOrGroup.type}</div>
                        <div>Values: {JSON.stringify(filterOrGroup)}</div>
                        <UniversalFilters
                            key={key}
                            pageKey={key}
                            filters={filterOrGroup}
                            addText="Add filter"
                            onAdd={() => setInnerGroupFilters([...filterOrGroup.values, {}], index)}
                            onChange={(index: number, property: any) => {
                                const newFilters = [...filterOrGroup.values]
                                newFilters.splice(index, 1, property)
                                setInnerGroupFilters(newFilters, index)
                            }}
                            onRemove={(index) => {
                                const newFilters = [...filterOrGroup.values]
                                newFilters.splice(index, 1)
                                setInnerGroupFilters(newFilters, index)
                            }}
                        />
                    </div>
                ) : (
                    <UniversalFilterRow
                        filter={filterOrGroup}
                        index={index}
                        pageKey={pageKey}
                        onRemove={_onRemove}
                        onChange={_onChange}
                    />
                )
            })}
            <LemonButton type="secondary" size="small" onClick={onAdd} icon={<IconPlusSmall />}>
                {addText}
            </LemonButton>
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

    useEffect(() => {
        setOpen(true)
    }, [])

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
