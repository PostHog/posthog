import { HogFunctionType } from '~/types'

import { IsDataPipelinesListEmptyProps, isDataPipelinesListEmpty } from './isDataPipelinesListEmpty'

describe('isDataPipelinesListEmpty', () => {
    const hogFunction = (id: string): HogFunctionType =>
        ({
            id,
            name: id,
            type: 'destination',
            enabled: true,
            hog: '',
        }) as HogFunctionType

    const props = (overrides: Partial<IsDataPipelinesListEmptyProps> = {}): IsDataPipelinesListEmptyProps => ({
        hogFunctions: [],
        hogFunctionsLoading: false,
        manualSources: [[], []],
        ...overrides,
    })

    it.each([
        { name: 'nothing exists', overrides: {}, expected: true },
        { name: 'a hog function exists', overrides: { hogFunctions: [hogFunction('hf')] }, expected: false },
        {
            name: 'a manual source has an entry',
            overrides: { manualSources: [[], [hogFunction('batch-export-1')]] },
            expected: false,
        },
        { name: 'hog functions are still loading', overrides: { hogFunctionsLoading: true }, expected: false },
        { name: 'a manual source has not resolved yet', overrides: { manualSources: [[], null] }, expected: false },
        { name: 'there are no manual sources', overrides: { manualSources: [] }, expected: true },
    ])('$name -> $expected', ({ overrides, expected }) => {
        expect(isDataPipelinesListEmpty(props(overrides))).toBe(expected)
    })
})
