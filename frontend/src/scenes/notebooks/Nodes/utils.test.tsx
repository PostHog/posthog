import { act, renderHook } from '@testing-library/react'
import { NodeViewProps } from '@tiptap/core'

import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import {
    INTEGER_REGEX_MATCH_GROUPS,
    SHORT_CODE_REGEX_MATCH_GROUPS,
    UUID_REGEX_MATCH_GROUPS,
    createUrlRegex,
    sortProperties,
    useSyncedAttributes,
} from './utils'

// Mock dependencies for Group revenue utilities
jest.mock('lib/utils', () => ({
    ...jest.requireActual('lib/utils'),
    percentage: jest.fn((value: number) => `${(value * 100).toFixed(1)}%`),
}))

jest.mock('lib/utils/geography/currency', () => ({
    formatCurrency: jest.fn((value: number) => `$${value.toFixed(2)}`),
}))

describe('notebook node utils', () => {
    jest.useFakeTimers()
    describe('useSyncedAttributes', () => {
        const harness: { node: { attrs: Record<string, any> }; updateAttributes: any } = {
            node: { attrs: {} },
            updateAttributes: jest.fn((attrs) => {
                harness.node.attrs = { ...harness.node.attrs, ...attrs }
            }),
        }

        const nodeViewProps = harness as unknown as NodeViewProps

        beforeEach(() => {
            harness.node.attrs = {
                foo: 'bar',
            }
            harness.updateAttributes.mockClear()
        })

        it('should set a default node ID', () => {
            const { result } = renderHook(() => useSyncedAttributes(nodeViewProps))

            expect(nodeViewProps.updateAttributes).not.toHaveBeenCalled()

            expect(result.current[0]).toEqual({
                nodeId: expect.any(String),
                foo: 'bar',
            })
        })

        it('should do nothing if an attribute is unchanged', () => {
            const { result } = renderHook(() => useSyncedAttributes(nodeViewProps))

            expect(nodeViewProps.updateAttributes).not.toHaveBeenCalled()

            expect(result.current[0]).toMatchObject({
                foo: 'bar',
            })

            act(() => {
                result.current[1]({
                    foo: 'bar',
                })
            })

            jest.runOnlyPendingTimers()

            expect(nodeViewProps.updateAttributes).not.toHaveBeenCalled()

            expect(result.current[0]).toMatchObject({
                foo: 'bar',
            })
        })

        it('should call the update attributes function if changed', () => {
            const { result, rerender } = renderHook(() => useSyncedAttributes(nodeViewProps))

            expect(nodeViewProps.updateAttributes).not.toHaveBeenCalled()

            act(() => {
                result.current[1]({
                    foo: 'bar2',
                })
            })

            jest.runOnlyPendingTimers()

            expect(nodeViewProps.updateAttributes).toHaveBeenCalledWith({
                foo: 'bar2',
            })

            rerender()

            expect(result.current[0]).toMatchObject({
                foo: 'bar2',
            })
        })

        it('should stringify and parse content', () => {
            harness.node.attrs = {
                filters: { my: 'data' },
                number: 1,
            }
            const { result, rerender } = renderHook(() => useSyncedAttributes(nodeViewProps))

            expect(result.current[0]).toEqual({
                nodeId: expect.any(String),
                filters: {
                    my: 'data',
                },
                number: 1,
            })

            act(() => {
                result.current[1]({
                    filters: {
                        my: 'changed data',
                    },
                })
            })

            jest.runOnlyPendingTimers()

            expect(nodeViewProps.updateAttributes).toHaveBeenCalledWith({
                filters: '{"my":"changed data"}',
            })

            rerender()

            expect(result.current[0]).toEqual({
                nodeId: expect.any(String),
                filters: {
                    my: 'changed data',
                },
                number: 1,
            })

            harness.updateAttributes.mockClear()

            act(() => {
                result.current[1]({
                    filters: {
                        my: 'changed data',
                    },
                })
            })

            jest.runOnlyPendingTimers()
            expect(nodeViewProps.updateAttributes).not.toHaveBeenCalled()
        })
    })

    describe('paste matching handlers', () => {
        it('matches the uuid regex', () => {
            let url = urls.replaySingle(UUID_REGEX_MATCH_GROUPS)
            let regex = createUrlRegex(url)
            let matches = regex.exec('http://localhost/replay/0192c471-b890-7546-9eae-056d98b8c5a8')
            expect(matches?.[1]).toEqual('0192c471-b890-7546-9eae-056d98b8c5a8')

            url = urls.experiment(INTEGER_REGEX_MATCH_GROUPS)
            regex = createUrlRegex(url)
            matches = regex.exec('http://localhost/experiments/12345')
            expect(matches?.[1]).toEqual('12345')

            url = urls.insightView(SHORT_CODE_REGEX_MATCH_GROUPS as InsightShortId)
            regex = createUrlRegex(url)
            matches = regex.exec('http://localhost/insights/TAg12F')
            expect(matches?.[1]).toEqual('TAg12F')
        })
        it('ignores any query params', () => {
            let url = urls.replaySingle(UUID_REGEX_MATCH_GROUPS)
            let regex = createUrlRegex(url)
            let matches = regex.exec('http://localhost/replay/0192c471-b890-7546-9eae-056d98b8c5a8?filters=false')
            expect(matches?.[1]).toEqual('0192c471-b890-7546-9eae-056d98b8c5a8')

            url = urls.insightView(SHORT_CODE_REGEX_MATCH_GROUPS as InsightShortId)
            regex = createUrlRegex(url)
            matches = regex.exec('http://localhost/insights/TAg12F?dashboardId=1234')
            expect(matches?.[1]).toEqual('TAg12F')
        })
    })

    describe('sortProperties', () => {
        describe('pinned properties take priority', () => {
            it('should place pinned properties before non-pinned ones', () => {
                const entries: [string, any][] = [
                    ['name', 'John'],
                    ['email', 'john@example.com'],
                    ['age', 25],
                ]
                const pinnedProperties = ['email']

                const result = sortProperties(entries, pinnedProperties)

                expect(result).toEqual([
                    ['email', 'john@example.com'],
                    ['age', 25],
                    ['name', 'John'],
                ])
            })

            it('should maintain pinned properties in their specified order', () => {
                const entries: [string, any][] = [
                    ['name', 'John'],
                    ['email', 'john@example.com'],
                    ['userId', '123'],
                    ['timestamp', '2023-01-01'],
                ]
                const pinnedProperties = ['userId', 'email', 'name']

                const result = sortProperties(entries, pinnedProperties)

                expect(result).toEqual([
                    ['userId', '123'],
                    ['email', 'john@example.com'],
                    ['name', 'John'],
                    ['timestamp', '2023-01-01'],
                ])
            })

            it('should sort non-pinned properties alphabetically after pinned ones', () => {
                const entries: [string, any][] = [
                    ['zebra', 'value1'],
                    ['apple', 'value2'],
                    ['priority', 'value3'],
                    ['banana', 'value4'],
                ]
                const pinnedProperties = ['priority']

                const result = sortProperties(entries, pinnedProperties)

                expect(result).toEqual([
                    ['priority', 'value3'],
                    ['apple', 'value2'],
                    ['banana', 'value4'],
                    ['zebra', 'value1'],
                ])
            })
        })

        describe('alphabetical sorting for non-pinned properties', () => {
            it('should sort all properties alphabetically when none are pinned', () => {
                const entries: [string, any][] = [
                    ['zebra', 'last'],
                    ['apple', 'first'],
                    ['middle', 'second'],
                    ['banana', 'third'],
                ]

                const result = sortProperties(entries, [])

                expect(result).toEqual([
                    ['apple', 'first'],
                    ['banana', 'third'],
                    ['middle', 'second'],
                    ['zebra', 'last'],
                ])
            })

            it('should handle case sensitivity in alphabetical sorting', () => {
                const entries: [string, any][] = [
                    ['Apple', 'capital'],
                    ['apple', 'lowercase'],
                    ['Zebra', 'capital-z'],
                ]

                const result = sortProperties(entries, [])

                expect(result).toEqual([
                    ['apple', 'lowercase'],
                    ['Apple', 'capital'],
                    ['Zebra', 'capital-z'],
                ])
            })

            it('should handle special characters properly', () => {
                const entries: [string, any][] = [
                    ['normal', 'regular'],
                    ['$special', 'dollar'],
                    ['_underscore', 'underscore'],
                    ['regular', 'alphabetic'],
                ]

                const result = sortProperties(entries, [])

                expect(result).toEqual([
                    ['_underscore', 'underscore'],
                    ['$special', 'dollar'],
                    ['normal', 'regular'],
                    ['regular', 'alphabetic'],
                ])
            })
        })

        describe('edge cases', () => {
            it('should handle empty entries array', () => {
                const result = sortProperties([], ['some', 'pinned'])
                expect(result).toEqual([])
            })

            it('should handle empty pinned properties', () => {
                const entries: [string, any][] = [
                    ['zebra', 'last'],
                    ['apple', 'first'],
                ]

                const result = sortProperties(entries, [])

                expect(result).toEqual([
                    ['apple', 'first'],
                    ['zebra', 'last'],
                ])
            })

            it('should handle properties not in pinned array', () => {
                const entries: [string, any][] = [
                    ['notPinned1', 'value1'],
                    ['notPinned2', 'value2'],
                ]
                const pinnedProperties = ['somethingElse']

                const result = sortProperties(entries, pinnedProperties)

                expect(result).toEqual([
                    ['notPinned1', 'value1'],
                    ['notPinned2', 'value2'],
                ])
            })

            it('should handle duplicate property names gracefully', () => {
                const entries: [string, any][] = [
                    ['same', 'value1'],
                    ['same', 'value2'],
                ]

                const result = sortProperties(entries, [])

                expect(result).toEqual([
                    ['same', 'value1'],
                    ['same', 'value2'],
                ])
            })
        })

        describe('real-world scenarios', () => {
            it('should sort PostHog event properties correctly', () => {
                const entries: [string, any][] = [
                    ['timestamp', '2023-01-01T10:00:00Z'],
                    ['$current_url', 'https://example.com'],
                    ['name', 'Button Click'],
                    ['$browser', 'Chrome'],
                    ['user_id', '12345'],
                ]
                const pinnedProperties = ['$current_url', '$browser']

                const result = sortProperties(entries, pinnedProperties)

                expect(result).toEqual([
                    ['$current_url', 'https://example.com'],
                    ['$browser', 'Chrome'],
                    ['name', 'Button Click'],
                    ['timestamp', '2023-01-01T10:00:00Z'],
                    ['user_id', '12345'],
                ])
            })

            it('should handle complex pinned order with many properties', () => {
                const entries: [string, any][] = [
                    ['prop5', 'value5'],
                    ['prop1', 'value1'],
                    ['unpinned', 'valueX'],
                    ['prop3', 'value3'],
                    ['another', 'valueY'],
                ]
                const pinnedProperties = ['prop1', 'prop2', 'prop3', 'prop4', 'prop5']

                const result = sortProperties(entries, pinnedProperties)

                expect(result).toEqual([
                    ['prop1', 'value1'],
                    ['prop3', 'value3'],
                    ['prop5', 'value5'],
                    ['another', 'valueY'],
                    ['unpinned', 'valueX'],
                ])
            })
        })
    })

    describe('Group revenue utilities', () => {
        const baseGroupData = {
            created_at: '2024-01-15T10:00:00Z',
            group_key: 'test-key',
            group_type_index: 0,
            group_properties: {},
            notebook: null,
        }

        describe('calculateMRRData', () => {
            test.each([
                {
                    name: 'returns null when mrr is missing',
                    group: baseGroupData,
                    expected: null,
                },
                {
                    name: 'returns null when mrr is null',
                    group: { ...baseGroupData, group_properties: { mrr: null } },
                    expected: null,
                },
                {
                    name: 'returns null when mrr is NaN',
                    group: { ...baseGroupData, group_properties: { mrr: 'not a number' } },
                    expected: null,
                },
                {
                    name: 'returns zero when mrr is zero',
                    group: { ...baseGroupData, group_properties: { mrr: 0 } },
                    expected: {
                        mrr: 0,
                        forecastedMrr: null,
                        percentageDiff: null,
                        tooltipText: null,
                        trendDirection: null,
                    },
                },
                {
                    name: 'returns data without forecast',
                    group: { ...baseGroupData, group_properties: { mrr: 1000 } },
                    expected: {
                        mrr: 1000,
                        forecastedMrr: null,
                        percentageDiff: null,
                        tooltipText: null,
                        trendDirection: null,
                    },
                },
                {
                    name: 'calculates positive trend',
                    group: { ...baseGroupData, group_properties: { mrr: 1000, forecasted_mrr: 1200 } },
                    expected: {
                        mrr: 1000,
                        forecastedMrr: 1200,
                        percentageDiff: 0.2,
                        tooltipText: '20.0% MRR growth forecasted to $1200.00',
                        trendDirection: 'up',
                    },
                },
                {
                    name: 'calculates negative trend',
                    group: { ...baseGroupData, group_properties: { mrr: 1000, forecasted_mrr: 800 } },
                    expected: {
                        mrr: 1000,
                        forecastedMrr: 800,
                        percentageDiff: -0.2,
                        tooltipText: '20.0% MRR decrease forecasted to $800.00',
                        trendDirection: 'down',
                    },
                },
                {
                    name: 'calculates flat trend',
                    group: { ...baseGroupData, group_properties: { mrr: 1000, forecasted_mrr: 1000 } },
                    expected: {
                        mrr: 1000,
                        forecastedMrr: 1000,
                        percentageDiff: 0,
                        tooltipText: 'No MRR change forecasted, flat at $1000.00',
                        trendDirection: 'flat',
                    },
                },
                {
                    name: 'handles negative MRR',
                    group: { ...baseGroupData, group_properties: { mrr: -100 } },
                    expected: {
                        mrr: -100,
                        forecastedMrr: null,
                        percentageDiff: null,
                        tooltipText: null,
                        trendDirection: null,
                    },
                },
            ])('$name', ({ group, expected }) => {
                const { calculateMRRData } = require('./utils')
                const result = calculateMRRData(group, 'USD')
                expect(result).toEqual(expected)
            })
        })

        describe('getPaidProducts', () => {
            test.each([
                {
                    name: 'returns empty array when mrr_per_product is missing',
                    group: baseGroupData,
                    expected: [],
                },
                {
                    name: 'returns empty array when mrr_per_product is empty',
                    group: { ...baseGroupData, group_properties: { mrr_per_product: {} } },
                    expected: [],
                },
                {
                    name: 'returns empty array when all products have zero MRR',
                    group: {
                        ...baseGroupData,
                        group_properties: { mrr_per_product: { product_a: 0, product_b: 0 } },
                    },
                    expected: [],
                },
                {
                    name: 'returns single formatted product',
                    group: {
                        ...baseGroupData,
                        group_properties: { mrr_per_product: { product_analytics: 100 } },
                    },
                    expected: ['Product analytics'],
                },
                {
                    name: 'returns multiple formatted products',
                    group: {
                        ...baseGroupData,
                        group_properties: {
                            mrr_per_product: { product_analytics: 100, feature_flags: 200, session_replay: 150 },
                        },
                    },
                    expected: ['Product analytics', 'Feature flags', 'Session replay'],
                },
                {
                    name: 'filters out zero MRR products and formats names',
                    group: {
                        ...baseGroupData,
                        group_properties: {
                            mrr_per_product: { product_analytics: 100, feature_flags: 0, session_replay: 150 },
                        },
                    },
                    expected: ['Product analytics', 'Session replay'],
                },
                {
                    name: 'filters out negative MRR products and formats names',
                    group: {
                        ...baseGroupData,
                        group_properties: { mrr_per_product: { product_a: -100, product_b: 200 } },
                    },
                    expected: ['Product b'],
                },
                {
                    name: 'formats complex product names with underscores',
                    group: {
                        ...baseGroupData,
                        group_properties: { mrr_per_product: { data_warehouse_analytics: 500 } },
                    },
                    expected: ['Data warehouse analytics'],
                },
                {
                    name: 'formats single word product names',
                    group: {
                        ...baseGroupData,
                        group_properties: { mrr_per_product: { experiments: 300 } },
                    },
                    expected: ['Experiments'],
                },
                {
                    name: 'filters out products with invalid MRR values',
                    group: {
                        ...baseGroupData,
                        group_properties: { mrr_per_product: { valid_product: 100, invalid_product: 'not_a_number' } },
                    },
                    expected: ['Valid product'],
                },
            ])('$name', ({ group, expected }) => {
                const { getPaidProducts } = require('./utils')
                const result = getPaidProducts(group)
                expect(result).toEqual(expected)
            })
        })

        describe('getLifetimeValue', () => {
            test.each([
                {
                    name: 'returns null when customer_lifetime_value is missing',
                    group: baseGroupData,
                    expected: null,
                },
                {
                    name: 'returns null when customer_lifetime_value is null',
                    group: { ...baseGroupData, group_properties: { customer_lifetime_value: null } },
                    expected: null,
                },
                {
                    name: 'returns null when customer_lifetime_value is not a number',
                    group: { ...baseGroupData, group_properties: { customer_lifetime_value: 'invalid' } },
                    expected: null,
                },
                {
                    name: 'returns lifetime value when present',
                    group: { ...baseGroupData, group_properties: { customer_lifetime_value: 5000 } },
                    expected: 5000,
                },
                {
                    name: 'returns zero when customer_lifetime_value is zero',
                    group: { ...baseGroupData, group_properties: { customer_lifetime_value: 0 } },
                    expected: 0,
                },
                {
                    name: 'returns negative value when customer_lifetime_value is negative',
                    group: { ...baseGroupData, group_properties: { customer_lifetime_value: -100 } },
                    expected: -100,
                },
            ])('$name', ({ group, expected }) => {
                const { getLifetimeValue } = require('./utils')
                expect(getLifetimeValue(group)).toBe(expected)
            })
        })
    })
})
