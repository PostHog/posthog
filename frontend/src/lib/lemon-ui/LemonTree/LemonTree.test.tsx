import '@testing-library/jest-dom'

import { act, render, screen, waitFor, within } from '@testing-library/react'
import { createRef } from 'react'

import { LemonTree, LemonTreeRef, TreeDataItem } from './LemonTree'

class ResizeObserverMock {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('LemonTree virtualization', () => {
    let requestAnimationFrameSpy: jest.SpyInstance<number, [FrameRequestCallback]>
    let cancelAnimationFrameSpy: jest.SpyInstance<void, [number]>

    beforeAll(() => {
        ;(global as typeof globalThis & { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
            ResizeObserverMock as unknown as typeof ResizeObserver
    })

    beforeEach(() => {
        jest.useRealTimers()
        requestAnimationFrameSpy = jest
            .spyOn(window, 'requestAnimationFrame')
            .mockImplementation((callback: FrameRequestCallback): number => {
                callback(performance.now())
                return 0
            })
        cancelAnimationFrameSpy = jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined)
    })

    afterEach(() => {
        requestAnimationFrameSpy.mockRestore()
        cancelAnimationFrameSpy.mockRestore()
    })

    const setViewportHeight = (container: HTMLElement, height: number): HTMLElement => {
        const viewport = container.querySelector('.ScrollableShadows__inner') as HTMLElement
        Object.defineProperty(viewport, 'clientHeight', { value: height, configurable: true })
        Object.defineProperty(viewport, 'scrollTop', { value: 0, writable: true, configurable: true })
        return viewport
    }

    const flushAnimationFrame = async (): Promise<void> => {
        await act(async () => {
            await new Promise<void>((resolve) => {
                requestAnimationFrame(() => resolve())
            })
        })
    }

    const scrollViewport = async (viewport: HTMLElement, scrollTop: number): Promise<void> => {
        act(() => {
            viewport.scrollTop = scrollTop
            viewport.dispatchEvent(new Event('scroll'))
        })
        await flushAnimationFrame()
    }

    it('renders only the visible window while scrolling', async () => {
        const data: TreeDataItem[] = [
            {
                id: 'root',
                name: 'root',
                children: Array.from({ length: 60 }, (_, index) => ({
                    id: `child-${index}`,
                    name: `child-${index}`,
                })),
            },
        ]

        const { container } = render(<LemonTree data={data} expandedItemIds={['root']} virtualized />)
        const viewport = setViewportHeight(container, 66)

        expect(screen.getByLabelText('tree item: child-0')).toBeInTheDocument()
        expect(screen.queryByLabelText('tree item: child-30')).not.toBeInTheDocument()

        act(() => {
            viewport.scrollTop = 31 * 30
            viewport.dispatchEvent(new Event('scroll'))
        })

        await waitFor(() => {
            expect(screen.getByLabelText('tree item: child-30')).toBeInTheDocument()
        })
        expect(screen.queryByLabelText('tree item: child-0')).not.toBeInTheDocument()
    })

    it('keeps ancestor rows mounted when focusing a deep descendant', async () => {
        const treeRef = createRef<LemonTreeRef>()
        const data: TreeDataItem[] = [
            {
                id: 'root',
                name: 'root',
                children: [
                    {
                        id: 'nested',
                        name: 'nested',
                        children: Array.from({ length: 60 }, (_, index) => ({
                            id: `grandchild-${index}`,
                            name: `grandchild-${index}`,
                        })),
                    },
                ],
            },
        ]

        const { container } = render(
            <LemonTree ref={treeRef} data={data} expandedItemIds={['root', 'nested']} virtualized />
        )
        setViewportHeight(container, 66)

        act(() => {
            treeRef.current?.focusItem('grandchild-50')
        })

        await waitFor(() => {
            expect(screen.getByLabelText('tree item: grandchild-50')).toBeInTheDocument()
        })

        const root = screen.getAllByLabelText('tree item: root')[0]
        const nested = screen.getAllByLabelText('tree item: nested')[0]
        const grandchild = screen.getByLabelText('tree item: grandchild-50')

        expect(root).toBeInTheDocument()
        expect(nested).toBeInTheDocument()
        expect(grandchild).toHaveAttribute('aria-level', '3')
        expect(document.activeElement).toBe(grandchild)
    })

    it('virtualizes against an outer scroll container when provided', async () => {
        const outerScrollRef = createRef<HTMLDivElement>()
        const data: TreeDataItem[] = [
            {
                id: 'root',
                name: 'root',
                children: Array.from({ length: 80 }, (_, index) => ({
                    id: `child-${index}`,
                    name: `child-${index}`,
                })),
            },
        ]

        const { container } = render(
            <div>
                <div style={{ height: 120 }} />
                <div ref={outerScrollRef}>
                    <LemonTree
                        data={data}
                        expandedItemIds={['root']}
                        virtualized
                        virtualizationScrollContainerRef={outerScrollRef}
                    />
                </div>
            </div>
        )

        const outerScroll = outerScrollRef.current as HTMLDivElement
        Object.defineProperty(outerScroll, 'clientHeight', { value: 66, configurable: true })
        Object.defineProperty(outerScroll, 'scrollTop', { value: 0, writable: true, configurable: true })

        const treeContent = outerScroll.querySelector('[class*="p-1"]') as HTMLElement
        jest.spyOn(treeContent, 'getBoundingClientRect').mockReturnValue({
            x: 0,
            y: 120,
            top: 120,
            bottom: 240,
            left: 0,
            right: 100,
            width: 100,
            height: 120,
            toJSON: () => ({}),
        })
        jest.spyOn(outerScroll, 'getBoundingClientRect').mockReturnValue({
            x: 0,
            y: 0,
            top: 0,
            bottom: 66,
            left: 0,
            right: 100,
            width: 100,
            height: 66,
            toJSON: () => ({}),
        })

        await scrollViewport(outerScroll, 120 + 31 * 40)

        await waitFor(() => {
            expect(within(container).getByLabelText('tree item: child-40')).toBeInTheDocument()
        })
    }, 10000)

    it('supports an overridden virtualized row height', async () => {
        const data: TreeDataItem[] = [
            {
                id: 'root',
                name: 'root',
                children: Array.from({ length: 80 }, (_, index) => ({
                    id: `child-${index}`,
                    name: `child-${index}`,
                })),
            },
        ]

        const { container } = render(
            <LemonTree data={data} expandedItemIds={['root']} virtualized virtualizedRowHeight={40} />
        )
        const viewport = setViewportHeight(container, 80)

        await scrollViewport(viewport, 40 * 30)

        await waitFor(() => {
            expect(within(container).getByLabelText('tree item: child-30')).toBeInTheDocument()
        })
        expect(within(container).queryByLabelText('tree item: child-0')).not.toBeInTheDocument()
    }, 10000)

    it('supports an overridden virtualization overscan', async () => {
        const data: TreeDataItem[] = [
            {
                id: 'root',
                name: 'root',
                children: Array.from({ length: 80 }, (_, index) => ({
                    id: `child-${index}`,
                    name: `child-${index}`,
                })),
            },
        ]

        const { container } = render(
            <LemonTree
                data={data}
                expandedItemIds={['root']}
                virtualized
                virtualizedRowHeight={31}
                virtualizedOverscan={0}
            />
        )
        const viewport = setViewportHeight(container, 62)

        await scrollViewport(viewport, 0)

        await waitFor(() => {
            expect(within(container).getByLabelText('tree item: child-0')).toBeInTheDocument()
        })
        expect(within(container).queryByLabelText('tree item: child-1')).not.toBeInTheDocument()
    }, 10000)
})
