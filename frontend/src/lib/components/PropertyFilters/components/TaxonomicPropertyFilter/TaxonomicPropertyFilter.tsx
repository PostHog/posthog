/*
Contains the property filter component w/ properties and cohorts separated in tabs. Also includes infinite-scroll remote loading.
*/
import './TaxonomicPropertyFilter.scss'
import React, { useMemo } from 'react'
import { Button, Input } from 'antd'
import { useValues, useActions, BindLogic } from 'kea'
import { PropertyFilterInternalProps } from '../PropertyFilter'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'

export enum DisplayMode {
    PROPERTY_SELECT = 'property_select',
    OPERATOR_VALUE_SELECT = 'operator_value_select',
}

let uniqueMemoizedIndex = 0

export function TaxonomicPropertyFilter({
    pageKey: pageKeyInput,
    index,
    onComplete,
}: PropertyFilterInternalProps): JSX.Element {
    const pageKey = useMemo(() => pageKeyInput || `filter-${uniqueMemoizedIndex++}`, [pageKeyInput])

    const { setFilter } = useActions(propertyFilterLogic)

    const logic = taxonomicPropertyFilterLogic({ pageKey, filterIndex: index })
    const { searchQuery, displayMode, filter } = useValues(logic)
    const { setSearchQuery, setDisplayMode } = useActions(logic)

    return (
        <div className="taxonomic-property-filter">
            <BindLogic logic={taxonomicPropertyFilterLogic} props={{ pageKey, filterIndex: index }}>
                {displayMode === DisplayMode.PROPERTY_SELECT && (
                    <>
                        <Input
                            autoFocus
                            placeholder="Search event or person properties"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                        <InfiniteSelectResults pageKey={pageKey} filterIndex={index} />
                    </>
                )}
                {displayMode === DisplayMode.OPERATOR_VALUE_SELECT && (
                    <div className="taxonomic-filter-row">
                        <Button onClick={() => setDisplayMode(DisplayMode.PROPERTY_SELECT)}>
                            <div style={{ display: 'flex' }}>
                                <PropertyKeyInfo value={filter?.key || ''} style={{ display: 'inline' }} />
                                <SelectDownIcon />
                            </div>
                        </Button>
                        <OperatorValueSelect
                            type={filter?.type}
                            propkey={filter?.key}
                            operator={filter?.operator}
                            value={filter?.value}
                            onChange={(newOperator, newValue) => {
                                if (filter?.key && filter?.type) {
                                    setFilter(index, filter?.key, newValue || null, newOperator, filter?.type)
                                }
                                if (
                                    newOperator &&
                                    newValue &&
                                    !isOperatorMulti(newOperator) &&
                                    !isOperatorRegex(newOperator)
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
            </BindLogic>
        </div>
    )
}
