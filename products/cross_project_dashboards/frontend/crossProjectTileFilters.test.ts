import { mergeTileFilters } from './crossProjectTileFilters'

describe('mergeTileFilters', () => {
    it.each([
        [
            'follows the dashboard when the tile overrides nothing',
            { date_from: '-30d', interval: 'day' },
            undefined,
            { date_from: '-30d', interval: 'day' },
        ],
        [
            'lets the tile win on the key it sets and keeps inheriting the rest',
            { date_from: '-30d', interval: 'week' },
            { date_from: '-7d' },
            { date_from: '-7d', interval: 'week' },
        ],
        [
            'does not treat an absent tile key as an override that clears the dashboard value',
            { date_from: '-30d' },
            { date_to: null, interval: null },
            { date_from: '-30d' },
        ],
        ['returns an empty set when neither side carries filters', undefined, undefined, {}],
    ] as const)('%s', (_label, dashboard, tile, expected) => {
        expect(mergeTileFilters(dashboard as any, tile as any)).toEqual(expected)
    })
})
