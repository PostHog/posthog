import clsx from 'clsx'
import { BindLogic } from 'kea'
import React from 'react'

import { IconCopy, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { AddBehavioralFilterButton } from 'lib/components/PropertyFilters/components/AddBehavioralFilterButton'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import { PropertyGroupFilterValue } from '~/types'

import { InsightTestAccountFilter } from '../filters/InsightTestAccountFilter'
import { AndOrFilterSelect } from './AndOrFilterSelect'
import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'
import type { PropertyGroupFiltersBodyProps } from './PropertyGroupFilters'

export function LemonPropertyGroupFilters({
    logicProps,
    insightProps,
    query,
    setQuery,
    pageKey,
    eventNames,
    taxonomicGroupTypes,
    propertyGroupFilter,
    groupRows,
    showHeader,
    disabledReason,
    behavioralFiltersEnabled,
    addFilterGroup,
    removeFilterGroup,
    duplicateFilterGroup,
    setOuterPropertyGroupsType,
    setInnerPropertyGroupType,
    setPropertyFilters,
}: PropertyGroupFiltersBodyProps): JSX.Element {
    return (
        <div className="deprecated-space-y-2 PropertyGroupFilters @container">
            {propertyGroupFilter.values && (
                <BindLogic logic={propertyGroupFilterLogic} props={logicProps}>
                    <div className="flex flex-col gap-2 @lg:flex-row @lg:items-center">
                        <div className="order-2 @lg:order-none PropertyGroupFilters__add-filter-group-inline-wrapper">
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
                        </div>
                        <div className="order-1 @lg:order-none">
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
                                            <div
                                                className={
                                                    behavioralFiltersEnabled
                                                        ? 'property-group--framed flex min-w-0 flex-col overflow-hidden rounded border'
                                                        : 'property-group'
                                                }
                                            >
                                                <div
                                                    className={clsx(
                                                        'flex items-center',
                                                        behavioralFiltersEnabled
                                                            ? 'gap-x-2 border-b px-2.5 py-2'
                                                            : 'justify-between mb-2'
                                                    )}
                                                >
                                                    <AndOrFilterSelect
                                                        onChange={(type) =>
                                                            setInnerPropertyGroupType(type, propertyGroupIndex)
                                                        }
                                                        value={group.type}
                                                        shortSuffix={behavioralFiltersEnabled ? 'in group' : undefined}
                                                    />
                                                    {!behavioralFiltersEnabled && (
                                                        <LemonDivider className="flex-1 mx-2 @max-[410px]/editor-panel:hidden" />
                                                    )}
                                                    <div
                                                        className={clsx(
                                                            'flex shrink-0 items-center gap-1',
                                                            behavioralFiltersEnabled && 'ml-auto'
                                                        )}
                                                    >
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
                                                <div
                                                    className={
                                                        behavioralFiltersEnabled
                                                            ? 'bg-primary px-2.5 py-2.5'
                                                            : undefined
                                                    }
                                                >
                                                    <PropertyFilters
                                                        addText="Filter"
                                                        propertyFilters={groupRows[propertyGroupIndex]}
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
                                                        logicalRowDivider={behavioralFiltersEnabled}
                                                        hasRowOperator={!behavioralFiltersEnabled}
                                                        addFilterDivider={behavioralFiltersEnabled}
                                                        addFilterSuffix={
                                                            behavioralFiltersEnabled
                                                                ? (addFilter) => (
                                                                      <AddBehavioralFilterButton
                                                                          data-attr={`${pageKey}-add-behavioral-filter`}
                                                                          onAdd={addFilter}
                                                                      />
                                                                  )
                                                                : null
                                                        }
                                                    />
                                                </div>
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
                        className="PropertyGroupFilters__add-filter-group-after"
                    >
                        Add filter group
                    </LemonButton>
                </BindLogic>
            )}
        </div>
    )
}
