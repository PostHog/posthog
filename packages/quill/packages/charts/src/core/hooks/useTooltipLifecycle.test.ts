import { renderHook, type RenderHookResult } from '@testing-library/react'
import { act } from 'react'

import type { TooltipContext } from '../types'
import { isTooltipContextEquivalent, useTooltipLifecycle } from './useTooltipLifecycle'

interface Meta {
    id: number
}

const FAKE_CANVAS_BOUNDS = {
    x: 0,
    y: 0,
    width: 800,
    height: 400,
    top: 0,
    right: 800,
    bottom: 400,
    left: 0,
    toJSON: () => ({}),
} as DOMRect

function makeCtx(overrides: Partial<TooltipContext<Meta>> = {}): TooltipContext<Meta> {
    return {
        dataIndex: 1,
        label: 'Tue',
        seriesData: [
            { series: { key: 'a', label: 'A', data: [1, 2, 3], meta: { id: 1 } }, value: 20, color: '#f00' },
            { series: { key: 'b', label: 'B', data: [5, 6, 7], meta: { id: 2 } }, value: 6, color: '#0f0' },
        ],
        position: { x: 100, y: 50 },
        hoverPosition: { x: 100, y: 50 },
        canvasBounds: FAKE_CANVAS_BOUNDS,
        isPinned: false,
        ...overrides,
    }
}

function makeRefs(): { wrapperRef: React.RefObject<HTMLDivElement> } {
    const wrapper = document.createElement('div')
    document.body.appendChild(wrapper)
    return { wrapperRef: { current: wrapper } }
}

type LifecycleResult = ReturnType<typeof useTooltipLifecycle<Meta>>

describe('useTooltipLifecycle', () => {
    let refs: { wrapperRef: React.RefObject<HTMLDivElement> }
    let rebuildPinnedCtx: jest.Mock<TooltipContext<Meta> | null, [TooltipContext<Meta>]>

    beforeEach(() => {
        jest.useFakeTimers()
        refs = makeRefs()
        // Default rebuild keeps the prev context. Tests override per-case.
        rebuildPinnedCtx = jest.fn((prev: TooltipContext<Meta>) => prev)
    })

    afterEach(() => {
        jest.useRealTimers()
        if (refs.wrapperRef.current) {
            document.body.removeChild(refs.wrapperRef.current)
        }
    })

    function renderLifecycle(
        rebuildDeps: React.DependencyList = []
    ): RenderHookResult<LifecycleResult, { rebuildDeps: React.DependencyList }> {
        return renderHook(
            ({ rebuildDeps }) =>
                useTooltipLifecycle<Meta>({
                    wrapperRef: refs.wrapperRef,
                    rebuildPinnedCtx,
                    rebuildDeps,
                }),
            { initialProps: { rebuildDeps } }
        )
    }

    function publishHoverCtx(result: { current: LifecycleResult }, ctx: TooltipContext<Meta> = makeCtx()): void {
        act(() => {
            result.current.setHover(ctx.dataIndex, ctx.hoverPosition)
            result.current.setTooltipCtx(ctx)
        })
    }

    function pinFromHover(result: { current: LifecycleResult }, ctx: TooltipContext<Meta> = makeCtx()): void {
        publishHoverCtx(result, ctx)
        act(() => {
            result.current.pin()
        })
        expect(result.current.isPinned).toBe(true)
    }

    it('starts empty', () => {
        const { result } = renderLifecycle()
        expect(result.current.tooltipCtx).toBeNull()
        expect(result.current.hoverIndex).toBe(-1)
        expect(result.current.hoverPosition).toBeNull()
        expect(result.current.isPinned).toBe(false)
    })

    it('publishes a hover tooltip via setHover + setTooltipCtx', () => {
        const { result } = renderLifecycle()
        publishHoverCtx(result)
        expect(result.current.tooltipCtx).not.toBeNull()
        expect(result.current.tooltipCtx!.isPinned).toBe(false)
        expect(result.current.hoverIndex).toBe(1)
        expect(result.current.hoverPosition).toEqual({ x: 100, y: 50 })
    })

    it('promotes hover ctx to pinned via pin()', () => {
        const { result } = renderLifecycle()
        pinFromHover(result)
        expect(result.current.tooltipCtx).not.toBeNull()
        expect(result.current.tooltipCtx!.onUnpin).toBeInstanceOf(Function)
    })

    it('pin() is a no-op when there is no current ctx', () => {
        const { result } = renderLifecycle()
        act(() => {
            result.current.pin()
        })
        expect(result.current.tooltipCtx).toBeNull()
        expect(result.current.isPinned).toBe(false)
    })

    it('unpin() drops only the pin, leaving hover state intact', () => {
        const { result } = renderLifecycle()
        pinFromHover(result)

        act(() => {
            result.current.unpin()
        })

        expect(result.current.tooltipCtx).toBeNull()
        expect(result.current.hoverIndex).toBe(1)
        expect(result.current.hoverPosition).toEqual({ x: 100, y: 50 })
    })

    it('clearTooltip() clears tooltip + hover state', () => {
        const { result } = renderLifecycle()
        pinFromHover(result)

        act(() => {
            result.current.clearTooltip()
        })

        expect(result.current.tooltipCtx).toBeNull()
        expect(result.current.hoverIndex).toBe(-1)
        expect(result.current.hoverPosition).toBeNull()
    })

    it.each<[string, () => void]>([
        ['Escape key', () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))],
        [
            'scroll outside the chart wrapper',
            () => {
                const outside = document.createElement('div')
                document.body.appendChild(outside)
                outside.dispatchEvent(new Event('scroll', { bubbles: true }))
                document.body.removeChild(outside)
            },
        ],
        [
            'click outside',
            () => {
                jest.runAllTimers()
                document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
            },
        ],
    ])('clears pinned tooltip on %s', (_name, trigger) => {
        const { result } = renderLifecycle()
        pinFromHover(result)

        act(() => {
            trigger()
        })

        expect(result.current.tooltipCtx).toBeNull()
    })

    it('does not clear pinned tooltip on non-Escape key', () => {
        const { result } = renderLifecycle()
        pinFromHover(result)

        act(() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
        })

        expect(result.current.tooltipCtx).not.toBeNull()
        expect(result.current.tooltipCtx!.isPinned).toBe(true)
    })

    it('does not clear pinned tooltip on click inside the wrapper', () => {
        const { result } = renderLifecycle()
        pinFromHover(result)
        act(() => {
            jest.runAllTimers()
        })

        act(() => {
            refs.wrapperRef.current!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })

        expect(result.current.tooltipCtx).not.toBeNull()
        expect(result.current.tooltipCtx!.isPinned).toBe(true)
    })

    it('does not clear pinned tooltip on scroll inside the tooltip element', () => {
        const { result } = renderLifecycle()
        pinFromHover(result)

        // Scrollable child of an element bearing the tooltip marker (the Tooltip overlay portals
        // outside the wrapper but tags itself with data-hog-charts-tooltip).
        const tooltipEl = document.createElement('div')
        tooltipEl.setAttribute('data-hog-charts-tooltip', '')
        const scrollableChild = document.createElement('div')
        tooltipEl.appendChild(scrollableChild)
        document.body.appendChild(tooltipEl)

        act(() => {
            scrollableChild.dispatchEvent(new Event('scroll', { bubbles: true }))
        })

        expect(result.current.tooltipCtx).not.toBeNull()
        expect(result.current.tooltipCtx!.isPinned).toBe(true)
        document.body.removeChild(tooltipEl)
    })

    it('does not clear pinned tooltip on scroll inside the chart wrapper', () => {
        const { result } = renderLifecycle()
        pinFromHover(result)

        const inner = document.createElement('div')
        refs.wrapperRef.current!.appendChild(inner)

        act(() => {
            inner.dispatchEvent(new Event('scroll', { bubbles: true }))
        })

        expect(result.current.tooltipCtx).not.toBeNull()
        expect(result.current.tooltipCtx!.isPinned).toBe(true)
    })

    it('clears unpinned tooltip on scroll outside the wrapper', () => {
        const { result } = renderLifecycle()
        publishHoverCtx(result)

        const outside = document.createElement('div')
        document.body.appendChild(outside)
        act(() => {
            outside.dispatchEvent(new Event('scroll', { bubbles: true }))
        })
        document.body.removeChild(outside)

        expect(result.current.tooltipCtx).toBeNull()
    })

    it('rebuilds the pinned tooltip when rebuildDeps change', () => {
        // Rebuild returns a fresh ctx with a different value so the equivalence bail doesn't kick in.
        const updated = makeCtx({
            seriesData: [
                { series: { key: 'a', label: 'A', data: [999, 999, 999], meta: { id: 1 } }, value: 999, color: '#f00' },
                { series: { key: 'b', label: 'B', data: [777, 777, 777], meta: { id: 2 } }, value: 777, color: '#0f0' },
            ],
        })
        rebuildPinnedCtx.mockImplementation(() => updated)

        const { result, rerender } = renderLifecycle([1])
        pinFromHover(result)

        const before = result.current.tooltipCtx
        expect(before).not.toBeNull()
        expect(before!.seriesData[0].value).toBe(20)

        rerender({ rebuildDeps: [2] })

        expect(rebuildPinnedCtx).toHaveBeenCalled()
        expect(result.current.tooltipCtx).not.toBeNull()
        expect(result.current.tooltipCtx!.isPinned).toBe(true)
        expect(result.current.tooltipCtx!.seriesData[0].value).toBe(999)
    })

    it('clears the pin when rebuildPinnedCtx returns null (data point gone)', () => {
        rebuildPinnedCtx.mockImplementation(() => null)
        const { result, rerender } = renderLifecycle([1])
        pinFromHover(result)

        rerender({ rebuildDeps: [2] })

        expect(result.current.tooltipCtx).toBeNull()
    })

    it('keeps the same tooltipCtx reference when the rebuild is value-equal (equivalence bail)', () => {
        // Return a clone with new identity but identical values.
        rebuildPinnedCtx.mockImplementation((prev) => ({ ...prev, seriesData: prev.seriesData.map((d) => ({ ...d })) }))
        const { result, rerender } = renderLifecycle([1])
        pinFromHover(result)

        const before = result.current.tooltipCtx
        rerender({ rebuildDeps: [2] })

        expect(result.current.tooltipCtx).toBe(before)
    })

    it('does not call rebuildPinnedCtx when not pinned', () => {
        const { result, rerender } = renderLifecycle([1])
        publishHoverCtx(result)
        rebuildPinnedCtx.mockClear()

        rerender({ rebuildDeps: [2] })

        expect(rebuildPinnedCtx).not.toHaveBeenCalled()
    })

    it('exposes onUnpin on the pinned ctx and the callback drops the pin', () => {
        const { result } = renderLifecycle()
        pinFromHover(result)
        expect(result.current.tooltipCtx).not.toBeNull()
        const onUnpin = result.current.tooltipCtx!.onUnpin
        expect(onUnpin).toBeInstanceOf(Function)

        act(() => {
            onUnpin!()
        })

        expect(result.current.tooltipCtx).toBeNull()
        // hover state untouched
        expect(result.current.hoverIndex).toBe(1)
    })
})

describe('isTooltipContextEquivalent', () => {
    const base = (): TooltipContext<Meta> => ({
        dataIndex: 1,
        label: 'Tue',
        seriesData: [
            { series: { key: 'a', label: 'A', data: [1, 2, 3] }, value: 20, color: '#f00' },
            { series: { key: 'b', label: 'B', data: [5, 6, 7] }, value: 6, color: '#0f0' },
        ],
        position: { x: 100, y: 50 },
        hoverPosition: { x: 100, y: 50 },
        canvasBounds: FAKE_CANVAS_BOUNDS,
        isPinned: false,
    })

    it.each<[string, (b: TooltipContext<Meta>) => TooltipContext<Meta>, boolean]>([
        ['identical', (b) => ({ ...b, seriesData: b.seriesData.map((d) => ({ ...d })) }), true],
        ['different dataIndex', (b) => ({ ...b, dataIndex: 2 }), false],
        ['different label', (b) => ({ ...b, label: 'Wed' }), false],
        ['different position.x', (b) => ({ ...b, position: { ...b.position, x: 999 } }), false],
        ['different position.y', (b) => ({ ...b, position: { ...b.position, y: 999 } }), false],
        ['different seriesData length', (b) => ({ ...b, seriesData: b.seriesData.slice(0, 1) }), false],
        [
            'different value',
            (b) => ({
                ...b,
                seriesData: [{ ...b.seriesData[0], value: 999 }, b.seriesData[1]],
            }),
            false,
        ],
        [
            'different color',
            (b) => ({
                ...b,
                seriesData: [{ ...b.seriesData[0], color: '#abc' }, b.seriesData[1]],
            }),
            false,
        ],
        [
            'different series.label (same key)',
            (b) => ({
                ...b,
                seriesData: [
                    { ...b.seriesData[0], series: { ...b.seriesData[0].series, label: 'A!' } },
                    b.seriesData[1],
                ],
            }),
            false,
        ],
        [
            'same key, new series identity, same values',
            (b) => ({
                ...b,
                seriesData: b.seriesData.map((d) => ({ ...d, series: { ...d.series } })),
            }),
            true,
        ],
    ])('%s -> %s', (_name, mutate, expected) => {
        expect(isTooltipContextEquivalent(base(), mutate(base()))).toBe(expected)
    })
})
