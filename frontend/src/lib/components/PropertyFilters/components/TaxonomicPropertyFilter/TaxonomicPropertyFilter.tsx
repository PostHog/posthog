/*
Contains the property filter component w/ properties and cohorts separated in tabs. Also includes infinite-scroll remote loading.
*/
import './TaxonomicPropertyFilter.scss'
import React, { useEffect, useMemo, useRef } from 'react'
import { Button, Card, Dropdown, Input } from 'antd'
import { useValues, useActions, BindLogic } from 'kea'
import { PropertyFilterInternalProps } from '../PropertyFilter'
import { InfiniteSelectResults } from './InfiniteSelectResults'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'

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

    const showInitialSearchInline = !disablePopover && !filter?.type && !filter?.key
    const showOperatorValueSelect = filter?.type && filter?.key && filter?.type !== 'cohort'

    const searchInput = (
        <Input
            placeholder="Search event or person properties"
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
                    selectSelected()
                }
            }}
        />
    )

    const searchResults = <InfiniteSelectResults pageKey={pageKey} filterIndex={index} focusInput={focusInput} />

    useEffect(() => {
        if (dropdownOpen || showInitialSearchInline) {
            window.setTimeout(() => focusInput(), 1)
        }
    }, [dropdownOpen, showInitialSearchInline])

    return (
        <div className="taxonomic-property-filter">
            <BindLogic logic={taxonomicPropertyFilterLogic} props={{ pageKey, filterIndex: index }}>
                <div className="taxonomic-filter-row">
                    {showInitialSearchInline ? (
                        <div className="taxonomic-filter-standalone">
                            {searchInput}
                            {searchResults}
                        </div>
                    ) : (
                        <Dropdown
                            overlay={
                                <Card className="taxonomic-filter-dropdown">
                                    {searchInput}
                                    {dropdownOpen ? searchResults : null}
                                </Card>
                            }
                            visible={dropdownOpen}
                            trigger={['click']}
                            onVisibleChange={(visible) => {
                                if (!visible) {
                                    closeDropdown()
                                }
                            }}
                        >
                            <Button onClick={() => openDropdown()}>
                                <div style={{ display: 'flex' }}>
                                    {filter?.type === 'cohort' ? (
                                        <span>{selectedCohortName || `Cohort #${filter?.value}`}</span>
                                    ) : filter?.key ? (
                                        <PropertyKeyInfo
                                            value={filter.key}
                                            style={{ display: 'inline' }}
                                            disablePopover
                                        />
                                    ) : (
                                        <span>Add filter</span>
                                    )}
                                    <SelectDownIcon />
                                </div>
                            </Button>
                        </Dropdown>
                    )}

                    {showOperatorValueSelect && (
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
                    )}
                </div>
            </BindLogic>
        </div>
    )
}
