import {
    dropDuplicatesOfOverrides,
    getDateRangeOverrideDisplay,
    getEffectiveFilterOverrides,
} from './insightDetailsFilterOverrides'

const browserChrome = { key: '$browser', value: 'Chrome', type: 'event', operator: 'exact' }
const browserSafari = { key: '$browser', value: 'Safari', type: 'event', operator: 'exact' }
const countryUS = { key: '$country', value: 'US', type: 'event', operator: 'exact' }

describe('InsightDetails', () => {
    describe('getDateRangeOverrideDisplay', () => {
        it.each([
            {
                label: 'backend-resolved tile date includes the replaced dashboard date',
                insightDateRange: { date_from: '-14d' },
                filterOverrideContext: {
                    dashboard: null,
                    tile: { date_from: '-7d' },
                    overridden_dashboard: { date_from: '-30d' },
                },
                filtersOverride: { date_from: '-30d' },
                tileFiltersOverride: { date_from: '-3d' },
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
        ])('$label', ({ insightDateRange, filterOverrideContext, filtersOverride, tileFiltersOverride, expected }) => {
            expect(
                getDateRangeOverrideDisplay(
                    insightDateRange,
                    filterOverrideContext,
                    filtersOverride,
                    tileFiltersOverride
                )
            ).toEqual(expected)
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
        it('renders the backend-resolved filter layers without recalculating conflicts', () => {
            const result = getEffectiveFilterOverrides(
                {
                    dashboard: { properties: [countryUS] } as any,
                    tile: { properties: [browserChrome] } as any,
                    overridden_dashboard: { properties: [browserSafari] } as any,
                },
                { properties: [browserSafari, countryUS] } as any,
                { properties: [browserChrome] } as any
            )

            expect(result.overriddenByTile).toEqual([browserSafari])
            expect(result.propertyGroups).toEqual([
                { properties: [countryUS], source: 'dashboard' },
                { properties: [browserChrome], source: 'tile' },
            ])
        })

        it('falls back to raw layers when no backend context exists', () => {
            const result = getEffectiveFilterOverrides(
                undefined,
                { properties: [countryUS] } as any,
                { properties: [browserChrome] } as any
            )

            expect(result.overriddenByTile).toEqual([])
            expect(result.propertyGroups).toEqual([
                { properties: [countryUS], source: 'dashboard' },
                { properties: [browserChrome], source: 'tile' },
            ])
        })

        it.each([
            {
                label: 'dashboard-only test account override',
                filtersOverride: { filterTestAccounts: true },
                tileFiltersOverride: undefined,
                expected: { filterTestAccounts: { value: true, source: 'dashboard' }, interval: null },
            },
            {
                label: 'force-off (false) still counts as a test account override',
                filtersOverride: { filterTestAccounts: false },
                tileFiltersOverride: undefined,
                expected: { filterTestAccounts: { value: false, source: 'dashboard' }, interval: null },
            },
            {
                label: 'dashboard-only interval override',
                filtersOverride: { interval: 'month' },
                tileFiltersOverride: undefined,
                expected: { filterTestAccounts: null, interval: { value: 'month', source: 'dashboard' } },
            },
            {
                label: 'tile scalar overrides beat dashboard ones',
                filtersOverride: { filterTestAccounts: true, interval: 'week' },
                tileFiltersOverride: { filterTestAccounts: false, interval: 'day' },
                expected: {
                    filterTestAccounts: { value: false, source: 'tile' },
                    interval: { value: 'day', source: 'tile' },
                },
            },
            {
                label: 'no scalar overrides set',
                filtersOverride: { properties: [countryUS] },
                tileFiltersOverride: undefined,
                expected: { filterTestAccounts: null, interval: null },
            },
        ])('$label', ({ filtersOverride, tileFiltersOverride, expected }) => {
            const result = getEffectiveFilterOverrides(undefined, filtersOverride as any, tileFiltersOverride as any)

            expect(result.filterTestAccounts).toEqual(expected.filterTestAccounts)
            expect(result.interval).toEqual(expected.interval)
        })

        it('resolves scalar overrides from the backend context layers, ignoring raw props', () => {
            const result = getEffectiveFilterOverrides(
                { dashboard: { filterTestAccounts: true, interval: 'week' }, tile: null } as any,
                { filterTestAccounts: false } as any,
                undefined
            )

            expect(result.filterTestAccounts).toEqual({ value: true, source: 'dashboard' })
            expect(result.interval).toEqual({ value: 'week', source: 'dashboard' })
        })
    })
})
