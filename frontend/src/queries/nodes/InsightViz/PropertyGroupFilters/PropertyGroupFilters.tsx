import { useValues, BindLogic, useActions } from 'kea'
import { PropertyGroupFilterValue, AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import './PropertyGroupFilters.scss'
import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isPropertyGroupFilterLike } from 'lib/components/PropertyFilters/utils'
import { GlobalFiltersTitle } from 'scenes/insights/common'
import { IconCopy, IconDelete, IconPlusMini } from 'lib/components/icons'
import { TestAccountFilter } from '../filters/TestAccountFilter'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import React from 'react'
import { InsightQueryNode, StickinessQuery, TrendsQuery } from '~/queries/schema'
import { AndOrFilterSelect } from './AndOrFilterSelect'

type PropertyGroupFiltersProps = {
    query: TrendsQuery | StickinessQuery
    setQuery: (node: TrendsQuery | StickinessQuery) => void
    pageKey: string
    eventNames?: string[]
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    noTitle?: boolean
}

export function PropertyGroupFilters({
    query,
    setQuery,
    pageKey,
    eventNames = [],
    taxonomicGroupTypes,
    noTitle,
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

    const showHeader = !noTitle || (propertyGroupFilter.type && propertyGroupFilter.values.length > 1)

    return (
        <div className="space-y-2 PropertyGroupFilters">
            {propertyGroupFilter.values && (
                <BindLogic logic={propertyGroupFilterLogic} props={logicProps}>
                    <TestAccountFilter query={query} setQuery={setQuery as (node: InsightQueryNode) => void} />
                    {showHeader ? (
                        <>
                            <div className="flex items-center justify-between">
                                {!noTitle ? <GlobalFiltersTitle orFiltering={true} /> : null}
                                {propertyGroupFilter.type && propertyGroupFilter.values.length > 1 && (
                                    <AndOrFilterSelect
                                        value={propertyGroupFilter.type}
                                        onChange={(value) => setOuterPropertyGroupsType(value)}
                                        topLevelFilter={true}
                                        suffix="groups"
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
                                                    <div className="flex-1 h-px mx-2 bg-dark-grey" />
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
                                                <PropertyFilters
                                                    addButton={
                                                        <LemonButton type="tertiary" noPadding icon={<IconPlusMini />}>
                                                            Add filter
                                                        </LemonButton>
                                                    }
                                                    propertyFilters={
                                                        isPropertyGroupFilterLike(group)
                                                            ? (group.values as AnyPropertyFilter[])
                                                            : null
                                                    }
                                                    style={{ marginBottom: 0 }}
                                                    onChange={(properties) => {
                                                        setPropertyFilters(properties, propertyGroupIndex)
                                                    }}
                                                    pageKey={`insight-filters-${propertyGroupIndex}`}
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
            >
                Add filter group
            </LemonButton>
        </div>
    )
}
