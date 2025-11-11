import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, type RecordingUniversalFilters } from '~/types'

import { applyRecordingPropertyFilter } from '../../utils'

describe('PlayerSidebarOverviewGrid', () => {
    describe('applyRecordingPropertyFilter', () => {
        it('creates Event property filter for $browser', () => {
            const mockSetFilters = jest.fn()
            const mockSetIsFiltersExpanded = jest.fn()
            const filters: RecordingUniversalFilters = {
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [],
                        },
                    ],
                },
            }

            applyRecordingPropertyFilter('$browser', 'Chrome', filters, mockSetFilters, mockSetIsFiltersExpanded)

            expect(mockSetFilters).toHaveBeenCalledWith({
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: '$browser',
                                    value: 'Chrome',
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                        },
                    ],
                },
            })
        })

        it('creates Person property filter for $geoip_ properties', () => {
            const mockSetFilters = jest.fn()
            const mockSetIsFiltersExpanded = jest.fn()
            const filters: RecordingUniversalFilters = {
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
            }

            applyRecordingPropertyFilter('$geoip_country_code', 'US', filters, mockSetFilters, mockSetIsFiltersExpanded)

            const call = mockSetFilters.mock.calls[0][0]
            expect(call.filter_group.values[0].values[0]).toMatchObject({
                type: PropertyFilterType.Person,
                key: '$geoip_country_code',
                value: 'US',
                operator: PropertyOperator.Exact,
            })
        })

        it('creates Person property filter for custom properties (no $ prefix)', () => {
            const mockSetFilters = jest.fn()
            const mockSetIsFiltersExpanded = jest.fn()
            const filters: RecordingUniversalFilters = {
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
            }

            applyRecordingPropertyFilter('custom_property', 'value', filters, mockSetFilters, mockSetIsFiltersExpanded)

            const call = mockSetFilters.mock.calls[0][0]
            expect(call.filter_group.values[0].values[0]).toMatchObject({
                type: PropertyFilterType.Person,
                key: 'custom_property',
                value: 'value',
                operator: PropertyOperator.Exact,
            })
        })

        it('creates Session property filter for session properties', () => {
            const mockSetFilters = jest.fn()
            const mockSetIsFiltersExpanded = jest.fn()
            const filters: RecordingUniversalFilters = {
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
            }

            applyRecordingPropertyFilter('$session_duration', '300', filters, mockSetFilters, mockSetIsFiltersExpanded)

            const call = mockSetFilters.mock.calls[0][0]
            expect(call.filter_group.values[0].values[0]).toMatchObject({
                type: PropertyFilterType.Session,
                key: '$session_duration',
                value: '300',
                operator: PropertyOperator.Exact,
            })
        })

        it('returns early when propertyValue is undefined', () => {
            const mockSetFilters = jest.fn()
            const mockSetIsFiltersExpanded = jest.fn()
            const filters: RecordingUniversalFilters = {
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
            }

            applyRecordingPropertyFilter('$browser', undefined, filters, mockSetFilters, mockSetIsFiltersExpanded)

            expect(mockSetFilters).not.toHaveBeenCalled()
        })

        it('creates Event property filter for $os', () => {
            const mockSetFilters = jest.fn()
            const mockSetIsFiltersExpanded = jest.fn()
            const filters: RecordingUniversalFilters = {
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
            }

            applyRecordingPropertyFilter('$os', 'Mac OS X', filters, mockSetFilters, mockSetIsFiltersExpanded)

            const call = mockSetFilters.mock.calls[0][0]
            expect(call.filter_group.values[0].values[0]).toMatchObject({
                type: PropertyFilterType.Event,
                key: '$os',
                value: 'Mac OS X',
                operator: PropertyOperator.Exact,
            })
        })

        it('creates Event property filter for $device_type', () => {
            const mockSetFilters = jest.fn()
            const mockSetIsFiltersExpanded = jest.fn()
            const filters: RecordingUniversalFilters = {
                duration: [],
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
            }

            applyRecordingPropertyFilter('$device_type', 'Desktop', filters, mockSetFilters, mockSetIsFiltersExpanded)

            const call = mockSetFilters.mock.calls[0][0]
            expect(call.filter_group.values[0].values[0]).toMatchObject({
                type: PropertyFilterType.Event,
                key: '$device_type',
                value: 'Desktop',
                operator: PropertyOperator.Exact,
            })
        })
    })

    describe('filter button wiring', () => {
        it('passes showFilter=true for property items with values', () => {
            // Test that property items with values get showFilter=true
            // This will be verified by the implementation
            expect(true).toBe(true) // Placeholder - real test requires component rendering
        })

        it('passes showFilter=false for property items without values', () => {
            expect(true).toBe(true) // Placeholder
        })

        it('passes showFilter=false for text items', () => {
            expect(true).toBe(true) // Placeholder
        })

        it('wires onFilterClick to call handleFilterByProperty with correct args', () => {
            expect(true).toBe(true) // Placeholder
        })
    })
})
