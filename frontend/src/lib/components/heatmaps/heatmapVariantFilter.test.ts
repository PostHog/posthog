import { variantFromEventFilters, variantToEventFilter } from 'lib/components/heatmaps/heatmapVariantFilter'
import { HeatmapEventFilter } from 'lib/components/heatmaps/types'

describe('heatmapVariantFilter', () => {
    it.each([
        ['no events', undefined, null],
        ['an unrelated event', [{ id: 'purchase', properties: [] }], null],
        [
            'a flag call without a variant',
            [{ id: '$feature_flag_called', properties: [{ key: '$feature_flag', value: 'checkout' }] }],
            null,
        ],
        [
            'the filter the variant picker builds',
            [variantToEventFilter({ flagKey: 'checkout', variant: 'test' })],
            { flagKey: 'checkout', variant: 'test' },
        ],
    ] as const)('reads the variant from %s', (_name, events, expected) => {
        expect(variantFromEventFilters(events as HeatmapEventFilter[] | undefined)).toEqual(expected)
    })
})
