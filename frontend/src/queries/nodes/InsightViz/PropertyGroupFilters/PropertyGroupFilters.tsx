import './PropertyGroupFilters.scss'

import { IconCopy, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isPropertyGroupFilterLike } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React from 'react'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightQueryNode, StickinessQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, InsightLogicProps, PropertyGroupFilterValue } from '~/types'

import { InsightTestAccountFilter } from '../filters/InsightTestAccountFilter'
import { AndOrFilterSelect } from './AndOrFilterSelect'
import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'

type PropertyGroupFiltersProps = {
    insightProps: InsightLogicProps
    query: TrendsQuery | StickinessQuery
    setQuery: (node: TrendsQuery | StickinessQuery) => void
    pageKey: string
    eventNames?: string[]
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    isDataWarehouseSeries?: boolean
}

export function PropertyGroupFilters({
    insightProps,
    query,
    setQuery,
    pageKey,
    eventNames = [],
    taxonomicGroupTypes,
    isDataWarehouseSeries,
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
    const disabledReason = isDataWarehouseSeries
        ? 'Cannot add filter groups to data warehouse series. Use individual series filters'
        : undefined
    return (
        <div className="deprecated-space-y-2 PropertyGroupFilters">
            {propertyGroupFilter.values && (
                <BindLogic logic={propertyGroupFilterLogic} props={logicProps}>
                    <div className="flex flex-1 gap-2 flex-row space-between">
                        <LemonButton
                            data-attr={`${pageKey}-add-filter-group-inline`}
                            type="secondary"
                            onClick={addFilterGroup}
                            icon={<IconPlusSmall />}
                            sideIcon={null}
                            disabledReason={disabledReason}
                            className="PropertyGroupFilters__add-filter-group-inline"
                        >
                            Add filter group
                        </LemonButton>

                        <div className="flex-1">
                            <InsightTestAccountFilter
                                disabledReason={disabledReason}
                                query={query}
                                setQuery={setQuery as (node: InsightQueryNode) => void}
                            />
                        </div>
                    </div>

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
                                                    <div className="flex items-center deprecated-space-x-2">
                                                        <LemonButton
                                                            icon={<IconCopy />}
                                                            onClick={() => duplicateFilterGroup(propertyGroupIndex)}
                                                            size="small"
                                                        />
                                                        <LemonButton
                                                            icon={<IconTrash />}
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

                    <LemonButton
                        data-attr={`${pageKey}-add-filter-group`}
                        type="secondary"
                        onClick={addFilterGroup}
                        icon={<IconPlusSmall />}
                        sideIcon={null}
                        disabledReason={disabledReason}
                        // This class hides this button in some situations to improve layout
                        // We don't want to hide it in Cypress tests because it'll complain the button isn't clickable
                        // so let's simply avoid adding the class in that case
                        className={clsx({
                            'PropertyGroupFilters__add-filter-group-after': !window.Cypress,
                        })}
                    >
                        Add filter group
                    </LemonButton>
                </BindLogic>
            )}
        </div>
    )
}
