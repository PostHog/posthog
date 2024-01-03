import { NodeViewProps } from '@tiptap/core'
import { useSyncedAttributes } from './utils'
import { renderHook, act } from '@testing-library/react-hooks'

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
})
