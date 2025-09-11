import { act, renderHook } from '@testing-library/react'
import { NodeViewProps } from '@tiptap/core'

import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import {
    INTEGER_REGEX_MATCH_GROUPS,
    SHORT_CODE_REGEX_MATCH_GROUPS,
    UUID_REGEX_MATCH_GROUPS,
    createUrlRegex,
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
})
