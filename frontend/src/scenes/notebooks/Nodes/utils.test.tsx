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
})
