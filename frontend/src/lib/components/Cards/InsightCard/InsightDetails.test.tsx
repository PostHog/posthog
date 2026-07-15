import { dropDuplicatesOfOverrides, getDateRangeOverrideDisplay, getEffectiveFilterOverrides } from './InsightDetails'

const browserChrome = { key: '$browser', value: 'Chrome', type: 'event', operator: 'exact' }
const browserSafari = { key: '$browser', value: 'Safari', type: 'event', operator: 'exact' }
const countryUS = { key: '$country', value: 'US', type: 'event', operator: 'exact' }

describe('InsightDetails', () => {
    describe('getDateRangeOverrideDisplay', () => {
        it.each([
            {
                label: 'tile date beats dashboard date (replaced = dashboard)',
                insightDateRange: { date_from: '-14d' },
                filtersOverride: { date_from: '-30d' },
                tileFiltersOverride: { date_from: '-7d' },
                expected: {
                    source: 'tile',
                    dateFrom: '-7d',
                    dateTo: undefined,
                    replaced: { source: 'dashboard', dateFrom: '-30d', dateTo: undefined },
                },
            },
            {
                label: 'tile date beats the insight range when no dashboard date (replaced = insight)',
                insightDateRange: { date_from: '-14d' },
                filtersOverride: undefined,
                tileFiltersOverride: { date_from: '-7d' },
                expected: {
                    source: 'tile',
                    dateFrom: '-7d',
                    dateTo: undefined,
                    replaced: { source: 'insight', dateFrom: '-14d', dateTo: undefined },
                },
            },
            {
                label: 'dashboard date beats the insight range (replaced = insight)',
                insightDateRange: { date_from: '-14d' },
                filtersOverride: { date_from: '-30d' },
                tileFiltersOverride: undefined,
                expected: {
                    source: 'dashboard',
                    dateFrom: '-30d',
                    dateTo: undefined,
                    replaced: { source: 'insight', dateFrom: '-14d', dateTo: undefined },
                },
            },
            {
                label: 'no override when only the insight has a date',
                insightDateRange: { date_from: '-14d' },
                filtersOverride: undefined,
                tileFiltersOverride: undefined,
                expected: null,
            },
            {
                label: 'no replaced value when the overridden layers have no date',
                insightDateRange: undefined,
                filtersOverride: undefined,
                tileFiltersOverride: { date_from: '-7d' },
                expected: { source: 'tile', dateFrom: '-7d', dateTo: undefined, replaced: undefined },
            },
            {
                label: 'replaced dropped when identical to the winning range',
                insightDateRange: { date_from: '-7d' },
                filtersOverride: undefined,
                tileFiltersOverride: { date_from: '-7d' },
                expected: { source: 'tile', dateFrom: '-7d', dateTo: undefined, replaced: undefined },
            },
        ])('$label', ({ insightDateRange, filtersOverride, tileFiltersOverride, expected }) => {
            expect(getDateRangeOverrideDisplay(insightDateRange, filtersOverride, tileFiltersOverride, true)).toEqual(
                expected
            )
        })
    })

    describe('dropDuplicatesOfOverrides', () => {
        it.each([
            {
                label: 'flat list: exact duplicate of an override is dropped',
                base: [browserChrome, countryUS],
                overrides: [browserChrome],
                expected: [countryUS],
            },
            {
                label: 'flat list: same key with a different value is kept (both genuinely AND)',
                base: [browserChrome, countryUS],
                overrides: [browserSafari],
                expected: [browserChrome, countryUS],
            },
            {
                label: 'flat list: same key+value but different operator is kept (identity includes operator)',
                base: [browserChrome],
                overrides: [{ ...browserChrome, operator: 'is_not' }],
                expected: [browserChrome],
            },
            {
                label: 'scalar and single-element-array values of the same filter are treated as duplicates',
                base: [{ key: '$email', value: 'a@b.com', type: 'person', operator: 'exact' }],
                overrides: [{ key: '$email', value: ['a@b.com'], type: 'person', operator: 'exact' }],
                expected: [],
            },
            {
                label: 'multi-value filters in a different order are treated as duplicates (values are a set)',
                base: [{ key: '$browser', value: ['Chrome', 'Safari'], type: 'event', operator: 'exact' }],
                overrides: [{ key: '$browser', value: ['Safari', 'Chrome'], type: 'event', operator: 'exact' }],
                expected: [],
            },
            {
                label: 'no overrides: base returned unchanged',
                base: [browserChrome],
                overrides: [],
                expected: [browserChrome],
            },
        ])('$label', ({ base, overrides, expected }) => {
            expect(dropDuplicatesOfOverrides(base as any, overrides as any)).toEqual(expected)
        })

        it('nested group: dedupes the matching leaf and prunes a subgroup left empty', () => {
            const base = {
                type: 'AND',
                values: [
                    { type: 'AND', values: [browserChrome, countryUS] },
                    { type: 'AND', values: [browserChrome] },
                ],
            }

            const result = dropDuplicatesOfOverrides(base as any, [browserChrome] as any) as any

            // The lone-duplicate subgroup is pruned; the mixed subgroup keeps its non-duplicate leaf.
            expect(result.values).toEqual([{ type: 'AND', values: [countryUS] }])
        })
    })

    describe('getEffectiveFilterOverrides', () => {
        it('captures a dashboard filter the tile shadows as overriddenByTile, out of the dashboard group', () => {
            const result = getEffectiveFilterOverrides(
                { properties: [browserSafari, countryUS] } as any,
                { properties: [browserChrome] } as any,
                true
            )

            // The dashboard's $browser lost to the tile's $browser — surfaced separately, not in the group.
            expect(result.overriddenByTile).toEqual([browserSafari])
            expect(result.propertyGroups).toEqual([
                { properties: [countryUS], source: 'dashboard' },
                { properties: [browserChrome], source: 'tile' },
            ])
        })

        it('keeps non-overlapping dashboard filters in the group with nothing overridden', () => {
            const result = getEffectiveFilterOverrides(
                { properties: [countryUS] } as any,
                { properties: [browserChrome] } as any,
                true
            )

            expect(result.overriddenByTile).toEqual([])
            expect(result.propertyGroups).toEqual([
                { properties: [countryUS], source: 'dashboard' },
                { properties: [browserChrome], source: 'tile' },
            ])
        })
    })
})
