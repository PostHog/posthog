import { filterNestedDataset } from './filterNestedDataset'
import { GraphDataset } from '~/types'

const sampleDatasets: GraphDataset[] = [
    {
        labels: ['Chrome', '$$_posthog_breakdown_other_$$', 'Firefox', 'Safari'],
        data: [13302, 12673, 6426, 4931],
        actions: [
            {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
                properties: {},
            },
            {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
                properties: {},
            },
            {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
                properties: {},
            },
            {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
                properties: {},
            },
        ],
        personsValues: [null, null, null, null],
        breakdownValues: [['Chrome'], ['$$_posthog_breakdown_other_$$'], ['Firefox'], ['Safari']],
        breakdownLabels: ['Chrome', 'Other (i.e. all remaining values)', 'Firefox', 'Safari'],
        compareLabels: [null, null, null, null],
        backgroundColor: ['#1d4aff', '#621da6', '#42827e', '#ce0e74'],
        hoverBackgroundColor: ['#1d4aff', '#621da6', '#42827e', '#ce0e74'],
        hoverBorderColor: ['#1d4aff', '#621da6', '#42827e', '#ce0e74'],
        borderColor: ['#1d4aff', '#621da6', '#42827e', '#ce0e74'],
        hoverBorderWidth: 10,
        borderWidth: 1,
    },
]

const filteredDatasets: GraphDataset[] = [
    {
        labels: ['Chrome', 'Safari'],
        data: [13302, 4931],
        actions: [
            {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
                properties: {},
            },
            {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: 'total',
                math_property: null,
                math_hogql: null,
                math_group_type_index: null,
                properties: {},
            },
        ],
        personsValues: [null, null],
        breakdownValues: [['Chrome'], ['Safari']],
        breakdownLabels: ['Chrome', 'Safari'],
        compareLabels: [null, null],
        backgroundColor: ['#1d4aff', '#ce0e74'],
        hoverBackgroundColor: ['#1d4aff', '#ce0e74'],
        hoverBorderColor: ['#1d4aff', '#ce0e74'],
        borderColor: ['#1d4aff', '#ce0e74'],
        hoverBorderWidth: 10,
        borderWidth: 1,
    },
]

describe('filterNestedDataset', () => {
    it('filters nested arrays using hiddenLegendIndexes', () => {
        const hiddenLegendIndexes = [1, 2]
        // const datasets: GraphDataset[] = [
        //     {
        //         actions: [{ custom_name: 'A' }, { custom_name: 'B' }],
        //         data: [1, 2],
        //     } as any,
        // ]
        const result = filterNestedDataset(hiddenLegendIndexes, sampleDatasets)
        expect(result).toEqual(filteredDatasets)
    })

    // it('filters nested arrays using hiddenLegendIndexes', () => {
    //     const hiddenLegendIndexes = [1]
    //     const datasets: GraphDataset[] = [
    //         {
    //             actions: [{ custom_name: 'A' }, { custom_name: 'B' }],
    //             data: [1, 2],
    //         } as any,
    //     ]
    //     const result = filterNestedDataset(hiddenLegendIndexes, datasets)
    //     expect(result[0].data).toEqual([1])
    // })

    // it('returns original values for non-array properties', () => {
    //     const hiddenLegendIndexes = undefined
    //     const datasets: GraphDataset[] = [
    //         {
    //             actions: [{ custom_name: 'A' }],
    //             value: 42,
    //         } as any,
    //     ]
    //     const result = filterNestedDataset(hiddenLegendIndexes, datasets)
    //     expect(result[0].value).toBe(42)
    // })
    // it('handles empty datasets', () => {
    //     const hiddenLegendIndexes = undefined
    //     const datasets: GraphDataset[] = []
    //     const result = filterNestedDataset(hiddenLegendIndexes, datasets)
    //     expect(result).toEqual([])
    // })
})
