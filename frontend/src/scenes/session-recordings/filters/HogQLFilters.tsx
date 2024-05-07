import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isPropertyGroupFilterLike } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'

import { actionsModel } from '~/models/actionsModel'
import { TestAccountFilter } from '~/queries/nodes/InsightViz/filters/TestAccountFilter'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { propertyGroupFilterLogic } from '~/queries/nodes/InsightViz/PropertyGroupFilters/propertyGroupFilterLogic'
import { getAllEventNames } from '~/queries/nodes/InsightViz/utils'
import { ReplayQuery } from '~/queries/schema'
import { AnyPropertyFilter, PropertyGroupFilterValue } from '~/types'

export default function HogQLFilters({
    query,
    setQuery,
}: {
    query: ReplayQuery
    setQuery: (node: ReplayQuery) => void
}): JSX.Element {
    const pageKey = 'session-recording'
    const logicProps = { query, setQuery, pageKey }
    const { propertyGroupFilter } = useValues(propertyGroupFilterLogic(logicProps))
    const {
        addFilterGroup,
        removeFilterGroup,
        duplicateFilterGroup,
        setOuterPropertyGroupsType,
        setInnerPropertyGroupType,
        setPropertyFilters,
    } = useActions(propertyGroupFilterLogic(logicProps))
    const { actions: allActions } = useValues(actionsModel)

    const hasMultipleGroups = propertyGroupFilter.values.length > 1
    const eventNames = getAllEventNames(query, allActions)

    return (
        <div className="flex flex-col mb-4 rounded border divide-y">
            <div className="flex justify-between px-1.5 p-1">
                <div className="flex items-center space-x-2">
                    <AndOrFilterSelect
                        value={propertyGroupFilter.type}
                        onChange={(value) => setOuterPropertyGroupsType(value)}
                        topLevelFilter={true}
                        suffix={['in', 'in']}
                    />
                    <DateFilter
                        dateFrom={query.dateRange?.date_from ?? '-7d'}
                        dateTo={query.dateRange?.date_to ?? undefined}
                        onChange={(changedDateFrom, changedDateTo) => {
                            setQuery?.({
                                ...query,
                                dateRange: {
                                    date_from: changedDateFrom ?? undefined,
                                    date_to: changedDateTo ?? undefined,
                                },
                            })
                        }}
                        size="small"
                        dateOptions={[
                            { key: 'Custom', values: [] },
                            { key: 'Last 24 hours', values: ['-24h'] },
                            { key: 'Last 7 days', values: ['-7d'] },
                            { key: 'Last 30 days', values: ['-30d'] },
                            { key: 'All time', values: ['-90d'] },
                        ]}
                    />
                </div>

                <div>
                    <TestAccountFilter query={query} setQuery={setQuery as (node: any) => void} />
                </div>
            </div>
            <div className="p-2 bg-bg-light rounded-b space-y-2">
                {propertyGroupFilter.values?.map((group: PropertyGroupFilterValue, propertyGroupIndex: number) => {
                    return (
                        <div
                            className={clsx('flex space-x-1', hasMultipleGroups && 'bg-side p-1 border rounded')}
                            key={propertyGroupIndex}
                        >
                            <PropertyFilters
                                addText="Add filter"
                                propertyFilters={
                                    isPropertyGroupFilterLike(group) ? (group.values as AnyPropertyFilter[]) : null
                                }
                                onChange={(properties) => {
                                    setPropertyFilters(properties, propertyGroupIndex)
                                }}
                                pageKey={`${pageKey}-PropertyGroupFilters-${propertyGroupIndex}`}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.SessionProperties,
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                ]}
                                eventNames={eventNames}
                                propertyGroupType={group.type}
                                allowNew
                            />
                        </div>
                    )
                })}

                <AddFilterProperty buttonText="Add group" addFilterGroup={addFilterGroup} />
            </div>
        </div>
    )
}

const AddFilterProperty = ({
    buttonText,
    addFilterGroup,
}: {
    buttonText: string
    addFilterGroup: (initialProperties?: (PropertyGroupFilterValue | AnyPropertyFilter)[] | undefined) => void
}): JSX.Element => {
    const [showPropertySelector, setShowPropertySelector] = useState<boolean>(false)

    return (
        <Popover
            visible={showPropertySelector}
            onClickOutside={() => setShowPropertySelector(false)}
            overlay={
                <TaxonomicFilter
                    onChange={() => {
                        // TODO: initialize filter group with the property
                        addFilterGroup()
                        setShowPropertySelector(false)
                    }}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.SessionProperties,
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                    ]}
                />
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                sideIcon={<IconPlusSmall />}
                onClick={() => setShowPropertySelector(!showPropertySelector)}
            >
                {buttonText}
            </LemonButton>
        </Popover>
    )
}
