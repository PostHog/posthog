import { formatHeatmapLabel, formatHeatmapValue, getHeatmapNullLabel, getHeatmapNullValue } from './heatmapUtils'

describe('formatHeatmapLabel', () => {
    it('uses the configured null label for nullish category values', () => {
        expect(formatHeatmapLabel(null, 'N/A')).toBe('N/A')
        expect(formatHeatmapLabel(undefined, 'N/A')).toBe('N/A')
        expect(formatHeatmapLabel('', 'N/A')).toBe('N/A')
        expect(formatHeatmapLabel('null', 'N/A')).toBe('N/A')
        expect(formatHeatmapLabel(' NULL ', 'N/A')).toBe('N/A')
    })

    it('defaults nullish category values to the string null', () => {
        expect(formatHeatmapLabel(null)).toBe('null')
        expect(formatHeatmapLabel(undefined)).toBe('null')
        expect(formatHeatmapLabel('')).toBe('null')
    })

    it('preserves non-null values', () => {
        expect(formatHeatmapLabel('nullify', 'N/A')).toBe('nullify')
        expect(formatHeatmapLabel('US', 'N/A')).toBe('US')
        expect(formatHeatmapLabel(0, 'N/A')).toBe('0')
    })
})

describe('formatHeatmapValue', () => {
    it('uses the configured null value for nullish cell values', () => {
        expect(formatHeatmapValue(null, 'N/A')).toBe('N/A')
        expect(formatHeatmapValue(undefined, 'N/A')).toBe('N/A')
        expect(formatHeatmapValue('', 'N/A')).toBe('N/A')
        expect(formatHeatmapValue('null', 'N/A')).toBe('N/A')
        expect(formatHeatmapValue(' NULL ', 'N/A')).toBe('N/A')
    })

    it('defaults nullish cell values to blank', () => {
        expect(formatHeatmapValue(null)).toBe('')
        expect(formatHeatmapValue(undefined)).toBe('')
        expect(formatHeatmapValue('')).toBe('')
    })

    it('preserves non-null cell values', () => {
        expect(formatHeatmapValue('nullify', 'N/A')).toBe('nullify')
        expect(formatHeatmapValue(0, 'N/A')).toBe('0')
    })
})

describe('getHeatmapNullValue', () => {
    it('defaults null values to blank', () => {
        expect(getHeatmapNullValue({})).toBe('')
    })

    it('uses the explicit null value when configured', () => {
        expect(getHeatmapNullValue({ nullLabel: 'null', nullValue: 'N/A' })).toBe('N/A')
    })

    it('stays blank when only a null label is configured', () => {
        expect(getHeatmapNullValue({ nullLabel: 'N/A' })).toBe('')
    })
})

describe('getHeatmapNullLabel', () => {
    it('defaults header null labels to the string null', () => {
        expect(getHeatmapNullLabel({})).toBe('null')
    })

    it('uses the label override for rendered heatmap headers', () => {
        expect(getHeatmapNullLabel({ nullLabel: 'N/A' })).toBe('N/A')
    })

    it('does not let the null value override affect heatmap headers', () => {
        expect(getHeatmapNullLabel({ nullLabel: 'N/A', nullValue: '(blank)' })).toBe('N/A')
    })
})
