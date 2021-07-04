/*
Contains the property filter component w/ properties and cohorts separated in tabs. Also includes infinite-scroll remote loading.
*/
import React from 'react'
import { Input, Button } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'
import { useValues, useActions } from 'kea'
import { OperatorValueSelect } from '../OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { PropertyOperator } from '~/types'
import { PropertyFilterInternalProps } from '../PropertyFilter'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/taxonomicPropertyFilterLogic'

import './TaxonomicPropertyFilter.scss'

export enum DisplayMode {
    PROPERTY_SELECT,
    OPERATOR_VALUE_SELECT,
}

export function TaxonomicPropertyFilter({
    pageKey = window.location.pathname,
    index,
    onComplete,
}: PropertyFilterInternalProps): JSX.Element {
    const { filters } = useValues(propertyFilterLogic)
    const { setFilter } = useActions(propertyFilterLogic)
    const { key, value, operator, type } = filters[index]
    const initialDisplayMode =
        key && type !== 'cohort' ? DisplayMode.OPERATOR_VALUE_SELECT : DisplayMode.PROPERTY_SELECT
    const filterKey = `${pageKey}-${index}`
    const logic = taxonomicPropertyFilterLogic({ key: filterKey, initialDisplayMode })
    const { personProperties, cohorts, searchQuery, displayMode } = useValues(logic)
    const { setSearchQuery, setSelectedItemKey, setDisplayMode } = useActions(logic)

    return (
        <div style={{ minWidth: '25rem' }}>
            {displayMode === DisplayMode.PROPERTY_SELECT && (
                <>
                    <Input
                        autoFocus
                        placeholder="Search event or person properties"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                    <InfiniteSelectResults
                        filterKey={filterKey}
                        groups={[
                            {
                                key: 'events',
                                name: 'Event properties',
                                type: 'event',
                                endpoint: 'api/projects/@current/property_definitions',
                            },
                            {
                                key: 'persons',
                                name: 'Person properties',
                                type: 'person',
                                dataSource: personProperties,
                            },
                            {
                                key: 'cohorts',
                                name: 'Cohort',
                                type: 'cohort',
                                dataSource: cohorts,
                            },
                        ]}
                        onSelect={(newType, newKey, name) => {
                            const newOperator = name === '$active_feature_flags' ? PropertyOperator.IContains : operator
                            setSelectedItemKey(newKey)
                            if (newType === 'cohort') {
                                setFilter(index, 'id', newKey, null, newType)
                            } else {
                                setFilter(
                                    index,
                                    name,
                                    null, // Reset value field
                                    newOperator || PropertyOperator.Exact,
                                    newType
                                )
                                setDisplayMode(DisplayMode.OPERATOR_VALUE_SELECT)
                            }
                        }}
                    />
                </>
            )}
            {displayMode === DisplayMode.OPERATOR_VALUE_SELECT && (
                <div className="taxonomic-filter-row">
                    <Button onClick={() => setDisplayMode(DisplayMode.PROPERTY_SELECT)}>
                        <div style={{ display: 'flex' }}>
                            <PropertyKeyInfo value={key || ''} style={{ display: 'inline' }} />
                            <SelectDownIcon />
                        </div>
                    </Button>
                    <OperatorValueSelect
                        type={type}
                        propkey={key}
                        operator={operator}
                        value={value}
                        onChange={(newOperator, newValue) => {
                            if (key && type) {
                                setFilter(index, key, newValue || null, newOperator, type)
                            }
                            if (
                                newOperator &&
                                newValue &&
                                !(isOperatorMulti(newOperator) || isOperatorRegex(newOperator))
                            ) {
                                onComplete()
                            }
                        }}
                        columnOptions={{
                            flex: 1,
                            style: {
                                maxWidth: '50vw',
                                minWidth: '6rem',
                            },
                        }}
                    />
                </div>
            )}
        </div>
    )
}
