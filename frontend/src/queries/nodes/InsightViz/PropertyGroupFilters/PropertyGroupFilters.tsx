import './PropertyGroupFilters.scss'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isPropertyGroupFilterLike } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconCopy, IconDelete, IconPlusMini } from 'lib/lemon-ui/icons'
import React from 'react'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightQueryNode, StickinessQuery, TrendsQuery } from '~/queries/schema'
import { AnyPropertyFilter, InsightLogicProps, PropertyGroupFilterValue } from '~/types'

import { TestAccountFilter } from '../filters/TestAccountFilter'
import { AndOrFilterSelect } from './AndOrFilterSelect'
import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'

type PropertyGroupFiltersProps = {
    insightProps: InsightLogicProps
    query: TrendsQuery | StickinessQuery
    setQuery: (node: TrendsQuery | StickinessQuery) => void
    pageKey: string
    eventNames?: string[]
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
}

export function PropertyGroupFilters({
    insightProps,
    query,
    setQuery,
    pageKey,
    eventNames = [],
    taxonomicGroupTypes,
}: PropertyGroupFiltersProps): JSX.Element {
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

    const showHeader = propertyGroupFilter.type && propertyGroupFilter.values.length > 1

    return (
        <div className="space-y-2 PropertyGroupFilters">
            {propertyGroupFilter.values && (
                <BindLogic logic={propertyGroupFilterLogic} props={logicProps}>
                    <TestAccountFilter query={query} setQuery={setQuery as (node: InsightQueryNode) => void} />
                    {showHeader ? (
                        <>
                            <div className="flex items-center justify-between">
                                {propertyGroupFilter.type && propertyGroupFilter.values.length > 1 && (
                                    <AndOrFilterSelect
                                        value={propertyGroupFilter.type}
                                        onChange={(value) => setOuterPropertyGroupsType(value)}
                                        topLevelFilter={true}
                                        suffix={['group', 'groups']}
                                    />
                                )}
                            </div>
                            <LemonDivider className="my-4" />
                        </>
                    ) : null}
                    {propertyGroupFilter.values?.length ? (
                        <div>
                            {propertyGroupFilter.values?.map(
                                (group: PropertyGroupFilterValue, propertyGroupIndex: number) => {
                                    return (
                                        <React.Fragment key={propertyGroupIndex}>
                                            <div className="property-group">
                                                <div className="flex justify-between items-center mb-2">
                                                    <AndOrFilterSelect
                                                        onChange={(type) =>
                                                            setInnerPropertyGroupType(type, propertyGroupIndex)
                                                        }
                                                        value={group.type}
                                                    />
                                                    <LemonDivider className="flex-1 mx-2" />
                                                    <div className="flex items-center space-x-2">
                                                        <LemonButton
                                                            icon={<IconCopy />}
                                                            status="primary-alt"
                                                            onClick={() => duplicateFilterGroup(propertyGroupIndex)}
                                                            size="small"
                                                        />
                                                        <LemonButton
                                                            icon={<IconDelete />}
                                                            status="primary-alt"
                                                            onClick={() => removeFilterGroup(propertyGroupIndex)}
                                                            size="small"
                                                        />
                                                    </div>
                                                </div>
                                                <PropertyFilters
                                                    addText="Add filter"
                                                    propertyFilters={
                                                        isPropertyGroupFilterLike(group)
                                                            ? (group.values as AnyPropertyFilter[])
                                                            : null
                                                    }
                                                    onChange={(properties) => {
                                                        setPropertyFilters(properties, propertyGroupIndex)
                                                    }}
                                                    pageKey={`${keyForInsightLogicProps('new')(
                                                        insightProps
                                                    )}-PropertyGroupFilters-${propertyGroupIndex}`}
                                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                                    eventNames={eventNames}
                                                    propertyGroupType={group.type}
                                                    orFiltering
                                                />
                                            </div>
                                            {propertyGroupIndex !== propertyGroupFilter.values.length - 1 && (
                                                <div className="property-group-and-or-separator">
                                                    <span>{propertyGroupFilter.type}</span>
                                                </div>
                                            )}
                                        </React.Fragment>
                                    )
                                }
                            )}
                        </div>
                    ) : null}
                </BindLogic>
            )}
            <LemonButton
                data-attr={`${pageKey}-add-filter-group`}
                type="secondary"
                onClick={addFilterGroup}
                icon={<IconPlusMini color="var(--primary)" />}
                sideIcon={null}
            >
                Add filter group
            </LemonButton>
        </div>
    )
}
