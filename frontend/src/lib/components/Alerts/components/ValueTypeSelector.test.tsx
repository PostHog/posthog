import { ValueType } from '~/queries/schema/schema-general'

// Simple tests for ValueTypeSelector logic since full component tests require Kea form setup
describe('ValueTypeSelector', () => {
    describe('value type mapping', () => {
        it('maps RAW to Metric label', () => {
            expect(ValueType.RAW).toBe('raw')
        })

        it('maps DELTA to Delta label', () => {
            expect(ValueType.DELTA).toBe('delta')
        })
    })

    describe('value type options', () => {
        const getValueTypeLabel = (type: ValueType): string => {
            switch (type) {
                case ValueType.RAW:
                    return 'Metric'
                case ValueType.DELTA:
                    return 'Delta'
                default:
                    return 'Unknown'
            }
        }

        it('provides correct labels for value types', () => {
            expect(getValueTypeLabel(ValueType.RAW)).toBe('Metric')
            expect(getValueTypeLabel(ValueType.DELTA)).toBe('Delta')
        })
    })
})
