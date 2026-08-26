import { HogFunctionType, HogFunctionTypeType } from '~/types'

import { isDataPipelinesListEmpty } from './isDataPipelinesListEmpty'

describe('isDataPipelinesListEmpty', () => {
    const hogFunction = (id: string): HogFunctionType =>
        ({
            id,
            name: id,
            type: 'destination',
            enabled: true,
            hog: '',
        }) as HogFunctionType

    const props = (
        overrides: Partial<Parameters<typeof isDataPipelinesListEmpty>[0]> & { kind?: HogFunctionTypeType } = {}
    ): Parameters<typeof isDataPipelinesListEmpty>[0] => ({
        kind: 'destination',
        hogFunctions: [],
        hogFunctionsLoading: false,
        hogFunctionPluginsDestinations: [],
        hogFunctionBatchExports: [],
        hogFunctionPluginsSiteApps: [],
        ...overrides,
    })

    it.each([
        { name: 'nothing exists', overrides: {}, expected: true },
        { name: 'a hog function exists', overrides: { hogFunctions: [hogFunction('hf')] }, expected: false },
        {
            name: 'a batch export exists',
            overrides: { hogFunctionBatchExports: [hogFunction('batch-export-1')] },
            expected: false,
        },
        {
            name: 'a legacy plugin destination exists',
            overrides: { hogFunctionPluginsDestinations: [hogFunction('plugin-1')] },
            expected: false,
        },
        { name: 'hog functions are still loading', overrides: { hogFunctionsLoading: true }, expected: false },
        { name: 'batch exports have not resolved yet', overrides: { hogFunctionBatchExports: null }, expected: false },
        {
            name: 'legacy plugin destinations have not resolved yet',
            overrides: { hogFunctionPluginsDestinations: null },
            expected: false,
        },
    ])('destinations: $name -> $expected', ({ overrides, expected }) => {
        expect(isDataPipelinesListEmpty(props(overrides))).toBe(expected)
    })

    it('ignores destination-only sources for other kinds', () => {
        expect(
            isDataPipelinesListEmpty(
                props({
                    kind: 'transformation',
                    hogFunctionBatchExports: null,
                    hogFunctionPluginsDestinations: null,
                })
            )
        ).toBe(true)
    })
})
