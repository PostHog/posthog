import { normalizeDotMatrixData } from './dotMatrixData'
import {
    getDotMatrixDemoDisplay,
    getDotMatrixDemoPresentation,
    getDotMatrixSelectionSummary,
} from './dotMatrixDemoData'
import {
    DOT_MATRIX_MOCK_ACCOUNTS,
    DOT_MATRIX_PRODUCT_COUNT_SCALE,
    DOT_MATRIX_USER_COUNT_SCALE,
    getDotMatrixAccountMeta,
    getDotMatrixMockDataset,
    type DotMatrixMockDatasetName,
} from './mocks'

describe('dot matrix demo data', () => {
    test.each([
        {
            datasetName: 'product_activity',
            selected: [],
            label: 'Products used',
            scale: DOT_MATRIX_PRODUCT_COUNT_SCALE,
        },
        {
            datasetName: 'product_activity',
            selected: ['pa'],
            label: 'Users of Product analytics',
            scale: DOT_MATRIX_USER_COUNT_SCALE,
        },
        {
            datasetName: 'product_activity',
            selected: ['pa', 'web', 'surveys'],
            label: 'Users of any of these 3 products',
            scale: DOT_MATRIX_USER_COUNT_SCALE,
        },
        {
            datasetName: 'people',
            selected: ['pa'],
            label: 'Users of Product analytics',
            scale: DOT_MATRIX_USER_COUNT_SCALE,
        },
        { datasetName: 'ci', selected: ['job-0'], label: 'Failing jobs', scale: DOT_MATRIX_PRODUCT_COUNT_SCALE },
    ])('keeps the $datasetName selected metric aligned with its label', ({ datasetName, selected, label, scale }) => {
        const presentation = getDotMatrixDemoPresentation(datasetName as DotMatrixMockDatasetName, selected)
        expect(presentation.legend.countLabel).toBe(label)
        expect(presentation.countScale).toEqual(scale)
    })

    it('keeps selected CI trends green and user trends blue', () => {
        expect(getDotMatrixDemoPresentation('ci', ['job-0']).trendColor).toBe('#36a352')
        expect(getDotMatrixDemoPresentation('product_activity', ['pa']).trendColor).toBe('#3b76d4')
    })

    it('keeps larger user counts inside the trend domain', () => {
        const dataset = getDotMatrixMockDataset('product_activity')
        const selected = dataset.series?.map((series) => series.key) ?? []
        const display = getDotMatrixDemoDisplay(dataset, 'product_activity', 'count', selected, 'family', 'acme')
        const maximum = Math.max(...[...display.trends.values()].flat())
        expect(maximum).toBeGreaterThan(12)
        expect(display.trendMax).toBe(maximum)
    })

    it('counts overlapping people once across three selected products', () => {
        const dataset = getDotMatrixMockDataset('product_activity')
        const cell = normalizeDotMatrixData(dataset).getCell('acme', 'week-0')
        expect(getDotMatrixSelectionSummary(cell, ['pa', 'web', 'surveys'])).toEqual({ distinct: 12, overlap: 4 })
        expect(
            getDotMatrixSelectionSummary({ ...cell, data: [...cell.data, ...cell.data] }, ['pa', 'web', 'surveys'])
        ).toEqual({ distinct: 12, overlap: 4 })
    })

    test.each([
        { selected: [], first: 9 },
        { selected: ['pa', 'web', 'surveys'], first: 12 },
    ])('uses the same count metric in the trend for $selected', ({ selected, first }) => {
        const dataset = getDotMatrixMockDataset('product_activity')
        const display = getDotMatrixDemoDisplay(dataset, 'product_activity', 'count', selected, 'family', 'acme')
        expect(display.trends.get('acme')?.[0]).toBe(first)
    })

    it('uses the generated people for both the account header and detail summary', () => {
        const dataset = getDotMatrixMockDataset('product_activity')
        const display = getDotMatrixDemoDisplay(dataset, 'product_activity', 'account', [], 'family', 'acme')
        expect(getDotMatrixAccountMeta(DOT_MATRIX_MOCK_ACCOUNTS[0], dataset.data, [])).toBe('10 products · 16 users')
        expect(display.activePeopleCount).toBe(16)
        expect(display.rowPeople.get('acme/pa')).toHaveLength(15)
    })
})
