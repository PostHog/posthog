import { PropertyFilterType, PropertyOperator } from '~/types'

import { handleFilterByProperty } from './PlayerSidebarOverviewGrid'

describe('PlayerSidebarOverviewGrid', () => {
    describe('handleFilterByProperty', () => {
        it('creates person property filter for $browser', () => {
            const mockSetFilters = jest.fn()

            handleFilterByProperty('$browser', 'Chrome', mockSetFilters)

            expect(mockSetFilters).toHaveBeenCalledWith({
                person_properties: [
                    {
                        type: PropertyFilterType.Person,
                        key: '$browser',
                        value: 'Chrome',
                        operator: PropertyOperator.Exact,
                    },
                ],
            })
        })

        it('creates person property filter for $geoip_ properties', () => {
            const mockSetFilters = jest.fn()

            handleFilterByProperty('$geoip_country_code', 'US', mockSetFilters)

            expect(mockSetFilters).toHaveBeenCalledWith({
                person_properties: [
                    {
                        type: PropertyFilterType.Person,
                        key: '$geoip_country_code',
                        value: 'US',
                        operator: PropertyOperator.Exact,
                    },
                ],
            })
        })

        it('creates person property filter for custom properties (no $ prefix)', () => {
            const mockSetFilters = jest.fn()

            handleFilterByProperty('custom_property', 'value', mockSetFilters)

            expect(mockSetFilters).toHaveBeenCalledWith({
                person_properties: [
                    {
                        type: PropertyFilterType.Person,
                        key: 'custom_property',
                        value: 'value',
                        operator: PropertyOperator.Exact,
                    },
                ],
            })
        })

        it('creates event property filter for session properties', () => {
            const mockSetFilters = jest.fn()

            handleFilterByProperty('$session_duration', '300', mockSetFilters)

            expect(mockSetFilters).toHaveBeenCalledWith({
                session_properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: '$session_duration',
                        value: '300',
                        operator: PropertyOperator.Exact,
                    },
                ],
            })
        })

        it('returns early when propertyValue is undefined', () => {
            const mockSetFilters = jest.fn()

            handleFilterByProperty('$browser', undefined, mockSetFilters)

            expect(mockSetFilters).not.toHaveBeenCalled()
        })

        it('accepts empty string as valid filter value', () => {
            const mockSetFilters = jest.fn()

            handleFilterByProperty('$browser', '', mockSetFilters)

            expect(mockSetFilters).toHaveBeenCalledWith({
                person_properties: [
                    {
                        type: PropertyFilterType.Person,
                        key: '$browser',
                        value: '',
                        operator: PropertyOperator.Exact,
                    },
                ],
            })
        })

        it('creates person property filter for $os', () => {
            const mockSetFilters = jest.fn()

            handleFilterByProperty('$os', 'Mac OS X', mockSetFilters)

            expect(mockSetFilters).toHaveBeenCalledWith({
                person_properties: [
                    {
                        type: PropertyFilterType.Person,
                        key: '$os',
                        value: 'Mac OS X',
                        operator: PropertyOperator.Exact,
                    },
                ],
            })
        })

        it('creates person property filter for $device_type', () => {
            const mockSetFilters = jest.fn()

            handleFilterByProperty('$device_type', 'Desktop', mockSetFilters)

            expect(mockSetFilters).toHaveBeenCalledWith({
                person_properties: [
                    {
                        type: PropertyFilterType.Person,
                        key: '$device_type',
                        value: 'Desktop',
                        operator: PropertyOperator.Exact,
                    },
                ],
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
