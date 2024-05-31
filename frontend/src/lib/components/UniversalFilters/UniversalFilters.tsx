import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ActionFilter, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { FilterRow } from '../PropertyFilters/components/FilterRow'
import { TaxonomicPropertyFilter } from '../PropertyFilters/components/TaxonomicPropertyFilter'
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
                    <FilterRow
                        index={index}
                        filters={[]}
                        item={filterOrGroup}
                        label={addText}
                        openOnInsert
                        pageKey={pageKey}
                        totalCount={1}
                        onRemove={_onRemove}
                        disablePopover={false}
                        filterComponent={(onComplete) => (
                            <TaxonomicPropertyFilter
                                key={index}
                                pageKey={pageKey}
                                index={index}
                                onComplete={onComplete}
                                disablePopover={false}
                                filters={[]}
                                setFilter={_onChange}
                            />
                        )}
                    />
                )

                // return (
                //     // <ActionFilterRow
                //     //     key={filter.uuid}
                //     //     typeKey={typeKey}
                //     //     filter={filter}
                //     //     index={index}
                //     //     filterCount={localFilters.length}
                //     //     showNestedArrow={showNestedArrow}
                //     //     singleFilter={singleFilter}
                //     //     hideFilter={hideFilter || readOnly}
                //     //     {...commonProps}
                //     // />
                // )
            })}
            <LemonButton type="secondary" size="small" onClick={onAdd} icon={<IconPlusSmall />}>
                {addText}
            </LemonButton>
        </div>
    )
}
