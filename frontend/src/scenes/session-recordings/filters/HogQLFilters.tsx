import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'

import { actionsModel } from '~/models/actionsModel'
import { TestAccountFilter } from '~/queries/nodes/InsightViz/filters/TestAccountFilter'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { propertyGroupFilterLogic } from '~/queries/nodes/InsightViz/PropertyGroupFilters/propertyGroupFilterLogic'
import { ReplayQuery } from '~/queries/schema'
import { PropertyGroupFilterValue } from '~/types'

export default function HogQLFilters({
    query,
    setQuery,
}: {
    query: ReplayQuery
    setQuery: (node: ReplayQuery) => void
}): JSX.Element {
    const [showPropertySelector, setShowPropertySelector] = useState<boolean>(false)
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

    console.log(query.predicates)

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
            <div className="p-2 bg-bg-light rounded-b">
                {propertyGroupFilter.values?.length ? (
                    propertyGroupFilter.values?.map((group: PropertyGroupFilterValue, propertyGroupIndex: number) => {
                        return (
                            <div key={propertyGroupIndex}>
                                <Popover
                                    visible={showPropertySelector}
                                    onClickOutside={() => setShowPropertySelector(false)}
                                    overlay={
                                        <PropertyFilters
                                            addText="Add to group"
                                            propertyFilters={group.values}
                                            onChange={(properties) => {
                                                setPropertyFilters(properties, propertyGroupIndex)
                                            }}
                                            pageKey={`${pageKey}-PropertyGroupFilters-${propertyGroupIndex}`}
                                            taxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.SessionProperties,
                                                TaxonomicFilterGroupType.Events,
                                                TaxonomicFilterGroupType.Actions,
                                                TaxonomicFilterGroupType.PersonProperties,
                                                TaxonomicFilterGroupType.Cohorts,
                                            ]}
                                            propertyGroupType={group.type}
                                            allowNew={false}
                                            openOnInsert
                                        />
                                    }
                                >
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        sideAction={{ icon: <IconTrash />, onClick: () => console.log('Delete') }}
                                        onClick={() => setShowPropertySelector(!showPropertySelector)}
                                    >
                                        Group description
                                    </LemonButton>
                                </Popover>
                                <span>AND/OR</span>
                            </div>
                        )
                    })
                ) : (
                    <Popover
                        visible={showPropertySelector}
                        onClickOutside={() => setShowPropertySelector(false)}
                        overlay={
                            <TaxonomicFilter
                                onChange={({ type }, value) => {
                                    const predicates = query.predicates || []
                                    setQuery({
                                        ...query,
                                        predicates: [
                                            ...predicates,
                                            {
                                                eventName:
                                                    TaxonomicFilterGroupType.Events === type ? (value as string) : null,
                                                properties: [],
                                            },
                                        ],
                                    })
                                }}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.SessionProperties,
                                    TaxonomicFilterGroupType.Events,
                                    TaxonomicFilterGroupType.Actions,
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.Cohorts,
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
                            Add filter group
                        </LemonButton>
                    </Popover>
                )}
            </div>
        </div>
    )
}
