import { FEATURE_FLAGS } from 'lib/constants'

import {
    MARKETING_INTEGRATION_CONFIGS,
    MarketingAnalyticsTableQuery,
    NativeMarketingSource,
    NodeKind,
    VALID_NATIVE_MARKETING_SOURCES,
} from '~/queries/schema/schema-general'
import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'

import { NativeSource } from './marketingAnalyticsLogic'
import {
    createMarketingTile,
    getEnabledNativeMarketingSources,
    getOrderBy,
    getSortedColumnsByArray,
    orderArrayByPreference,
    rowMatchesSearch,
    validColumnsForTiles,
} from './utils'

describe('marketing analytics utils', () => {
    describe('getEnabledNativeMarketingSources', () => {
        it.each([
            ['filters out BingAds when flag is disabled', { [FEATURE_FLAGS.BING_ADS_SOURCE]: false }, 'BingAds', false],
            ['includes BingAds when flag is enabled', { [FEATURE_FLAGS.BING_ADS_SOURCE]: true }, 'BingAds', true],
            ['filters out BingAds with empty feature flags', {}, 'BingAds', false],
            [
                'filters out SnapchatAds when flag is disabled',
                { [FEATURE_FLAGS.SNAPCHAT_ADS_SOURCE]: false },
                'SnapchatAds',
                false,
            ],
            [
                'includes SnapchatAds when flag is enabled',
                { [FEATURE_FLAGS.SNAPCHAT_ADS_SOURCE]: true },
                'SnapchatAds',
                true,
            ],
            ['filters out SnapchatAds with empty feature flags', {}, 'SnapchatAds', false],
        ])('%s', (_name, featureFlags, source, shouldInclude) => {
            const result = getEnabledNativeMarketingSources(featureFlags ?? {})
            expect(result.includes(source as any)).toBe(shouldInclude)
        })

        it('always includes sources without feature flag requirements', () => {
            const sourcesWithoutFlags = VALID_NATIVE_MARKETING_SOURCES.filter(
                (s) => s !== 'BingAds' && s !== 'SnapchatAds'
            )
            const result = getEnabledNativeMarketingSources({})
            sourcesWithoutFlags.forEach((source) => {
                expect(result).toContain(source)
            })
        })
    })

    describe('getOrderBy', () => {
        it('should filter order by columns that exist in the columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
                orderBy: [
                    ['campaign', 'ASC'],
                    ['source', 'DESC'],
                    ['non_existent_column', 'ASC'],
                ],
            }
            const columns = ['campaign', 'source', 'other_column']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(2)
            expect(result.some((order) => order[0] === 'campaign' && order[1] === 'ASC')).toBe(true)
            expect(result.some((order) => order[0] === 'source' && order[1] === 'DESC')).toBe(true)
            expect(result.some((order) => order[0] === 'non_existent_column')).toBe(false)
        })

        it('should return empty array when query is undefined', () => {
            const columns = ['campaign', 'source']

            const result = getOrderBy(undefined, columns)

            expect(result.length).toBe(0)
        })

        it('should return empty array when query has no orderBy', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
            }
            const columns = ['campaign', 'source']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should return empty array when no order by columns exist in columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
                orderBy: [
                    ['non_existent_column', 'ASC'],
                    ['another_non_existent', 'DESC'],
                ],
            }
            const columns = ['campaign', 'source']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should handle empty columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign'],
                orderBy: [['campaign', 'ASC']],
            }
            const columns: string[] = []

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should preserve order of valid order by columns', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source', 'medium'],
                orderBy: [
                    ['campaign', 'ASC'],
                    ['non_existent', 'DESC'],
                    ['source', 'DESC'],
                    ['medium', 'ASC'],
                ],
            }
            const columns = ['campaign', 'source', 'medium']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(3)
            expect(result[0][0]).toBe('campaign')
            expect(result[1][0]).toBe('source')
            expect(result[2][0]).toBe('medium')
        })
    })

    describe('orderArrayByPreference', () => {
        it('should order array by preference with items in preference first', () => {
            const array = ['a', 'b', 'c']
            const preference = ['c', 'b']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['b', 'c', 'a'])
        })

        it('should handle empty preference array', () => {
            const array = ['a', 'b', 'c']
            const preference: string[] = []

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['a', 'b', 'c'])
        })

        it('should handle empty array', () => {
            const array: string[] = []
            const preference = ['c', 'b']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual([])
        })

        it('should handle preference with items not in array', () => {
            const array = ['a', 'b', 'c']
            const preference = ['d', 'e', 'b']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['b', 'a', 'c'])
        })

        it('should handle duplicate items in preference', () => {
            const array = ['a', 'b', 'c']
            const preference = ['b', 'b', 'c']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['b', 'c', 'a'])
        })

        it('should preserve order within preference groups', () => {
            const array = ['a', 'b', 'c', 'd']
            const preference = ['c', 'a']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['a', 'c', 'b', 'd'])
        })
    })

    describe('getSortedColumnsByArray', () => {
        it('should sort columns by sortedArray order', () => {
            const array = ['a', 'b', 'c']
            const sortedArray = ['c', 'b']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['c', 'b', 'a'])
        })

        it('should handle empty sortedArray', () => {
            const array = ['a', 'b', 'c']
            const sortedArray: string[] = []

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['a', 'b', 'c'])
        })

        it('should handle empty array', () => {
            const array: string[] = []
            const sortedArray = ['c', 'b']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual([])
        })

        it('should handle sortedArray with items not in array', () => {
            const array = ['a', 'b', 'c']
            const sortedArray = ['d', 'e', 'b', 'f']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['b', 'a', 'c'])
        })

        it('should handle duplicate items in sortedArray', () => {
            const array = ['a', 'b', 'c']
            const sortedArray = ['b', 'b', 'c', 'b']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['b', 'c', 'a'])
        })

        it('should preserve order of items not in sortedArray', () => {
            const array = ['a', 'b', 'c', 'd', 'e']
            const sortedArray = ['c', 'a']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['c', 'a', 'b', 'd', 'e'])
        })

        it('should handle case where all items are in sortedArray', () => {
            const array = ['a', 'b', 'c', 'a']
            const sortedArray = ['c', 'a', 'b', 'b']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['c', 'a', 'a', 'b'])
        })

        it('should handle case where no items are in sortedArray', () => {
            const array = ['a', 'b', 'c']
            const sortedArray = ['d', 'e', 'f']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['a', 'b', 'c'])
        })
    })

    describe('createMarketingTile snapshots', () => {
        const ALL_TILE_COLUMNS: validColumnsForTiles[] = [
            'cost',
            'impressions',
            'clicks',
            'reported_conversion',
            'reported_conversion_value',
            'roas',
        ]

        // All fields each source could reference, so the mock table has them all
        const sourceFields: Record<NativeMarketingSource, string[]> = {
            GoogleAds: [
                'metrics_cost_micros',
                'metrics_impressions',
                'metrics_clicks',
                'metrics_conversions',
                'metrics_conversions_value',
                'customer_currency_code',
            ],
            RedditAds: [
                'spend',
                'impressions',
                'clicks',
                'conversion_purchase_total_items',
                'conversion_purchase_total_value',
                'conversion_signup_total_value',
                'currency',
            ],
            LinkedinAds: [
                'cost_in_usd',
                'impressions',
                'clicks',
                'external_website_conversions',
                'conversion_value_in_local_currency',
            ],
            MetaAds: ['spend', 'impressions', 'clicks', 'actions', 'action_values', 'account_currency'],
            TikTokAds: ['spend', 'impressions', 'clicks', 'conversion', 'total_complete_payment_value', 'currency'],
            BingAds: ['spend', 'impressions', 'clicks', 'conversions', 'revenue', 'currency_code'],
            SnapchatAds: [
                'spend',
                'impressions',
                'swipes',
                'conversion_purchases',
                'conversion_purchases_value',
                'conversion_sign_ups',
                'conversion_sign_ups_value',
                'conversion_subscribe',
                'conversion_subscribe_value',
                'currency',
            ],
        }

        // Minimal fields: only non-conversion columns (cost, impressions, clicks, currency)
        const minimalSourceFields: Record<NativeMarketingSource, string[]> = {
            GoogleAds: ['metrics_cost_micros', 'metrics_impressions', 'metrics_clicks', 'customer_currency_code'],
            RedditAds: ['spend', 'impressions', 'clicks', 'currency'],
            LinkedinAds: ['cost_in_usd', 'impressions', 'clicks'],
            MetaAds: ['spend', 'impressions', 'clicks', 'account_currency'],
            TikTokAds: ['spend', 'impressions', 'clicks', 'currency'],
            BingAds: ['spend', 'impressions', 'clicks', 'currency_code'],
            SnapchatAds: ['spend', 'impressions', 'swipes', 'currency'],
        }

        function makeMockSource(sourceType: NativeMarketingSource, fieldList: string[]): NativeSource {
            const config = MARKETING_INTEGRATION_CONFIGS[sourceType]
            const fields = Object.fromEntries(
                fieldList.map((f) => [f, { name: f, type: 'string' }])
            ) as DatabaseSchemaDataWarehouseTable['fields']

            return {
                source: {
                    id: `${sourceType}-id`,
                    source_id: `${sourceType}-source-id`,
                    connection_id: `${sourceType}-conn`,
                    status: 'completed',
                    source_type: sourceType,
                    prefix: null,
                    description: null,
                    latest_error: null,
                    schemas: [],
                } as any,
                tables: [
                    {
                        id: `${sourceType}-stats-table-id`,
                        name: `prefix.${config.statsTableName}`,
                        type: 'data_warehouse',
                        format: 'Parquet',
                        url_pattern: '',
                        fields,
                    } as DatabaseSchemaDataWarehouseTable,
                ],
            }
        }

        const testCases = VALID_NATIVE_MARKETING_SOURCES.flatMap((sourceType) =>
            ALL_TILE_COLUMNS.map(
                (column) =>
                    [`${sourceType} - ${column}`, sourceType, column] as [
                        string,
                        NativeMarketingSource,
                        validColumnsForTiles,
                    ]
            )
        )

        it.each(testCases)('%s', (_name, sourceType, column) => {
            const source = makeMockSource(sourceType, sourceFields[sourceType])
            const result = createMarketingTile(source, column, 'USD')
            expect(result).toMatchSnapshot()
        })

        const missingFieldsCases = VALID_NATIVE_MARKETING_SOURCES.flatMap((sourceType) =>
            (['reported_conversion', 'reported_conversion_value', 'roas'] as validColumnsForTiles[]).map(
                (column) =>
                    [`${sourceType} - ${column} (missing conversion fields)`, sourceType, column] as [
                        string,
                        NativeMarketingSource,
                        validColumnsForTiles,
                    ]
            )
        )

        it.each(missingFieldsCases)('%s', (_name, sourceType, column) => {
            const source = makeMockSource(sourceType, minimalSourceFields[sourceType])
            const result = createMarketingTile(source, column, 'USD')
            expect(result).toMatchSnapshot()
        })
    })

    describe('rowMatchesSearch', () => {
        it.each([
            ['empty search term returns true', { result: ['test'] }, '', true],
            ['whitespace-only search returns true', { result: ['test'] }, '   ', true],
            ['null record returns false', null, 'test', false],
            ['undefined record returns false', undefined, 'test', false],
            ['non-object record returns false', 'string', 'test', false],
            ['row with label always returns true', { label: 'Total', result: [] }, 'anything', true],
            ['row without result array returns false', { other: 'data' }, 'test', false],
            ['row with non-array result returns false', { result: 'not-array' }, 'test', false],
            ['string match in result', { result: ['Google Ads', 'campaign'] }, 'google', true],
            ['case-insensitive string match', { result: ['FACEBOOK'] }, 'facebook', true],
            ['object with value string match', { result: [{ value: 'utm_source' }] }, 'utm', true],
            ['mixed array with match', { result: ['text', { value: 'match' }, 123] }, 'match', true],
            ['no match returns false', { result: ['alpha', 'beta'] }, 'gamma', false],
            ['object without value property no match', { result: [{ other: 'test' }] }, 'test', false],
            ['numeric values in result no match', { result: [123, 456] }, '123', false],
        ])('%s', (_name, record, searchTerm, expected) => {
            expect(rowMatchesSearch(record, searchTerm)).toBe(expected)
        })
    })
})
