/*
Contains the property filter component w/ properties and cohorts separated in tabs. Also includes infinite-scroll remote loading.
*/
import './TaxonomicPropertyFilter.scss'
import React, { useEffect, useMemo, useRef } from 'react'
import { Button, Col, Input } from 'antd'
import { useValues, useActions, BindLogic } from 'kea'
import { PropertyFilterInternalProps } from '../PropertyFilter'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { Popup } from 'lib/components/Popup/Popup'

let uniqueMemoizedIndex = 0

export function TaxonomicPropertyFilter({
    pageKey: pageKeyInput,
    index,
    onComplete,
    disablePopover,
}: PropertyFilterInternalProps): JSX.Element {
    const pageKey = useMemo(() => pageKeyInput || `filter-${uniqueMemoizedIndex++}`, [pageKeyInput])

    const searchInputRef = useRef<Input | null>(null)
    const focusInput = (): void => searchInputRef.current?.focus()

    const { setFilter } = useActions(propertyFilterLogic)

    const logic = taxonomicPropertyFilterLogic({ pageKey, filterIndex: index })
    const { searchQuery, filter, dropdownOpen, selectedCohortName } = useValues(logic)
    const {
        setSearchQuery,
        openDropdown,
        closeDropdown,
        moveUp,
        moveDown,
        tabLeft,
        tabRight,
        selectSelected,
    } = useActions(logic)

    const showInitialSearchInline = !disablePopover && ((!filter?.type && !filter?.key) || filter?.type === 'cohort')
    const showOperatorValueSelect = filter?.type && filter?.key && filter?.type !== 'cohort'

    const searchInput = (
        <Input
            placeholder="Search cohorts, event or person properties"
            value={searchQuery}
            ref={(ref) => (searchInputRef.current = ref)}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
                if (e.key === 'ArrowUp') {
                    e.preventDefault()
                    moveUp()
                }
                if (e.key === 'ArrowDown') {
                    e.preventDefault()
                    moveDown()
                }
                if (e.key === 'Tab') {
                    e.preventDefault()
                    if (e.shiftKey) {
                        tabLeft()
                    } else {
                        tabRight()
                    }
                }
                if (e.key === 'Enter') {
                    e.preventDefault()
                    selectSelected(onComplete)
                }
            }}
        />
    )

    const searchResults = (
        <InfiniteSelectResults pageKey={pageKey} filterIndex={index} focusInput={focusInput} onComplete={onComplete} />
    )

    useEffect(() => {
        if (dropdownOpen || showInitialSearchInline) {
            window.setTimeout(() => focusInput(), 1)
        }
    }, [dropdownOpen, showInitialSearchInline])

    return (
        <div className={`taxonomic-property-filter${!disablePopover ? ' in-dropdown' : ' row-on-page'}`}>
            <BindLogic logic={taxonomicPropertyFilterLogic} props={{ pageKey, filterIndex: index }}>
                {showInitialSearchInline ? (
                    <div className="taxonomic-filter-dropdown">
                        {searchInput}
                        {searchResults}
                    </div>
                ) : (
                    <div className="taxonomic-filter-row">
                        <Col className="taxonomic-where">
                            {index === 0 ? (
                                <>
                                    <span className="arrow">&#8627;</span>
                                    <span className="text">where</span>
                                </>
                            ) : (
                                <span className="stateful-badge and" style={{ fontSize: '90%' }}>
                                    AND
                                </span>
                            )}
                        </Col>

                        <Popup
                            overlay={
                                dropdownOpen ? (
                                    <div className="taxonomic-filter-dropdown">
                                        {searchInput}
                                        {searchResults}
                                    </div>
                                ) : null
                            }
                            placement={'bottom-start'}
                            fallbackPlacements={['bottom-end']}
                            visible={dropdownOpen}
                            onClickOutside={closeDropdown}
                        >
                            <Button
                                className={`taxonomic-button${!filter?.type && !filter?.key ? ' add-filter' : ''}`}
                                onClick={() => (dropdownOpen ? closeDropdown() : openDropdown())}
                            >
                                {filter?.type === 'cohort' ? (
                                    <div>{selectedCohortName || `Cohort #${filter?.value}`}</div>
                                ) : filter?.key ? (
                                    <PropertyKeyInfo value={filter.key} disablePopover />
                                ) : (
                                    <div>Add filter</div>
                                )}
                                <SelectDownIcon />
                            </Button>
                        </Popup>

                        {showOperatorValueSelect && (
                            <OperatorValueSelect
                                type={filter?.type}
                                propkey={filter?.key}
                                operator={filter?.operator}
                                value={filter?.value}
                                placeholder="Enter value..."
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
                                columnOptions={[
                                    {
                                        className: 'taxonomic-operator',
                                    },
                                    {
                                        className: 'taxonomic-value-select',
                                    },
                                ]}
                            />
                        )}
                    </div>
                )}
            </BindLogic>
        </div>
    )
}
