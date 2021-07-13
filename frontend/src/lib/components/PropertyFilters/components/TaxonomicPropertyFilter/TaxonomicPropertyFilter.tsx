/*
Contains the property filter component w/ properties and cohorts separated in tabs. Also includes infinite-scroll remote loading.
*/
import React, { useMemo } from 'react'
import { Input } from 'antd'
import { useValues, useActions, BindLogic } from 'kea'
import { PropertyOperator } from '~/types'
import { PropertyFilterInternalProps } from '../PropertyFilter'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'

import './TaxonomicPropertyFilter.scss'

export enum DisplayMode {
    PROPERTY_SELECT,
    OPERATOR_VALUE_SELECT,
}

let count = 0

export function TaxonomicPropertyFilter({ pageKey: pageKeyInput, index }: PropertyFilterInternalProps): JSX.Element {
    const pageKey = useMemo(() => pageKeyInput || `filter-${count++}`, [pageKeyInput])

    const { filters } = useValues(propertyFilterLogic)
    const { setFilter } = useActions(propertyFilterLogic)

    const logic = taxonomicPropertyFilterLogic({ pageKey, index })
    const { searchQuery, displayMode } = useValues(logic)
    const { setSearchQuery, setSelectedItemKey } = useActions(logic)

    return (
        <div style={{ minWidth: 'max(25rem, 40vw)' }}>
            <BindLogic logic={taxonomicPropertyFilterLogic} props={{ pageKey, index }}>
                {displayMode === DisplayMode.PROPERTY_SELECT && (
                    <>
                        <Input
                            autoFocus
                            placeholder="Search event or person properties"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                        <InfiniteSelectResults
                            pageKey={pageKey}
                            filterIndex={index}
                            onSelect={(newType, newKey, name) => {
                                const { operator } = filters[index] || {}
                                const newOperator =
                                    name === '$active_feature_flags' ? PropertyOperator.IContains : operator
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
                                }
                            }}
                        />
                    </>
                )}
                {/*{displayMode === DisplayMode.OPERATOR_VALUE_SELECT && (*/}
                {/*    <div className="taxonomic-filter-row">*/}
                {/*        <Button onClick={() => setDisplayMode(DisplayMode.PROPERTY_SELECT)}>*/}
                {/*            <div style={{ display: 'flex' }}>*/}
                {/*                <PropertyKeyInfo value={key || ''} style={{ display: 'inline' }} />*/}
                {/*                <SelectDownIcon />*/}
                {/*            </div>*/}
                {/*        </Button>*/}
                {/*        <OperatorValueSelect*/}
                {/*            type={type}*/}
                {/*            propkey={key}*/}
                {/*            operator={operator}*/}
                {/*            value={value}*/}
                {/*            onChange={(newOperator, newValue) => {*/}
                {/*                if (key && type) {*/}
                {/*                    setFilter(index, key, newValue || null, newOperator, type)*/}
                {/*                }*/}
                {/*                if (*/}
                {/*                    newOperator &&*/}
                {/*                    newValue &&*/}
                {/*                    !(isOperatorMulti(newOperator) || isOperatorRegex(newOperator))*/}
                {/*                ) {*/}
                {/*                    onComplete()*/}
                {/*                }*/}
                {/*            }}*/}
                {/*            columnOptions={{*/}
                {/*                flex: 1,*/}
                {/*                style: {*/}
                {/*                    maxWidth: '50vw',*/}
                {/*                    minWidth: '6rem',*/}
                {/*                },*/}
                {/*            }}*/}
                {/*        />*/}
                {/*    </div>*/}
                {/*)}*/}
            </BindLogic>
        </div>
    )
}
