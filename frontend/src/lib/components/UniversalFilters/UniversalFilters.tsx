import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ActionFilter, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

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
    filters = null,
    __isRoot = true,
    onAdd: _onAdd,
}: {
    pageKey: string
    filters: UniversalFiltersLogicProps['filters']
    onAdd: () => void
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
                            __isRoot={false}
                            onAdd={() => setInnerGroupFilters([...filterOrGroup.values, {}], index)}
                        />
                    </div>
                ) : (
                    <div>Action or Property</div>
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
                Add filter {__isRoot && 'group'}
            </LemonButton>
        </div>
    )
}
