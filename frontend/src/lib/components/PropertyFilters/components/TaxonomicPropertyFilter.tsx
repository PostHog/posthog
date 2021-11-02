import './TaxonomicPropertyFilter.scss'
import React, { useMemo } from 'react'
import { Button, Col } from 'antd'
import { useActions, useValues } from 'kea'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'
import { SelectDownIcon } from 'lib/components/SelectDownIcon'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { Popup } from 'lib/components/Popup/Popup'
import { PropertyFilterInternalProps } from 'lib/components/PropertyFilters'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    propertyFilterTypeToTaxonomicFilterType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'

let uniqueMemoizedIndex = 0

export function TaxonomicPropertyFilter({
    pageKey: pageKeyInput,
    index,
    onComplete,
    disablePopover, // inside a dropdown if this is false
    taxonomicGroupTypes,
}: PropertyFilterInternalProps): JSX.Element {
    const pageKey = useMemo(() => pageKeyInput || `filter-${uniqueMemoizedIndex++}`, [pageKeyInput])
    const { setFilter } = useActions(propertyFilterLogic)

    const logic = taxonomicPropertyFilterLogic({ pageKey, filterIndex: index })
    const { filter, dropdownOpen, selectedCohortName } = useValues(logic)
    const { openDropdown, closeDropdown, selectItem } = useActions(logic)

    const showInitialSearchInline = !disablePopover && ((!filter?.type && !filter?.key) || filter?.type === 'cohort')
    const showOperatorValueSelect = filter?.type && filter?.key && filter?.type !== 'cohort'

    // We don't support array filter values here. Multiple-cohort only supported in TaxonomicBreakdownFilter.
    // This is mostly to make TypeScript happy.
    const cohortOrOtherValue =
        filter?.type === 'cohort' ? (!Array.isArray(filter?.value) && filter?.value) || undefined : filter?.key

    const taxonomicFilter = (
        <TaxonomicFilter
            groupType={propertyFilterTypeToTaxonomicFilterType(filter?.type)}
            value={cohortOrOtherValue}
            onChange={(groupType, value) => {
                selectItem(taxonomicFilterTypeToPropertyFilterType(groupType), value)
                if (groupType === TaxonomicFilterGroupType.Cohorts) {
                    onComplete?.()
                }
            }}
            taxonomicGroupTypes={
                taxonomicGroupTypes || [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                ]
            }
        />
    )

    return (
        <div className={`taxonomic-property-filter${!disablePopover ? ' in-dropdown large' : ' row-on-page'}`}>
            {showInitialSearchInline ? (
                taxonomicFilter
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
                        overlay={dropdownOpen ? taxonomicFilter : null}
                        placement={'bottom-start'}
                        fallbackPlacements={['bottom-end']}
                        visible={dropdownOpen}
                        onClickOutside={closeDropdown}
                    >
                        <Button
                            data-attr={'property-select-toggle-' + index}
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
        </div>
    )
}
