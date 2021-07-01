/*
Contains the property filter component w/ properties and cohorts separated in tabs. Also includes infinite-scroll remote loading.
*/
import React, { useState } from 'react'
import { Input, Button } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'
import { useValues, useActions } from 'kea'
import { OperatorValueSelect } from './OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { PropertyOperator } from '~/types'
import { PropertyFilterInternalProps } from './PropertyFilter'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { propertyFilterLogic } from '../propertyFilterLogic'
import { taxonomicPropertyFilterLogic } from '../taxonomicPropertyFilterLogic'

import './TaxonomicPropertyFilter.scss'

export enum DisplayMode {
    PROPERTY_SELECT,
    OPERATOR_VALUE_SELECT,
}

export function TaxonomicPropertyFilter({ pageKey, index, onComplete }: PropertyFilterInternalProps): JSX.Element {
    const { filters } = useValues(propertyFilterLogic)
    const { personProperties, cohorts } = useValues(
        taxonomicPropertyFilterLogic({ pageKey: pageKey || window.location.pathname, index })
    )
    const { setFilter } = useActions(propertyFilterLogic)
    const { key, value, operator, type } = filters[index]

    const [searchQuery, setSearchQuery] = useState('')
    const [selectedItemKey, setSelectedItemKey] = useState<string | number | null>(null)
    const initialDisplayMode =
        key && type !== 'cohort' ? DisplayMode.OPERATOR_VALUE_SELECT : DisplayMode.PROPERTY_SELECT
    const [displayMode, setDisplayMode] = useState(initialDisplayMode)

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
                        defaultActiveTabKey={type ? type + 's' : undefined}
                        searchQuery={searchQuery}
                        selectedItemKey={selectedItemKey}
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
