import { act } from '@testing-library/react'

import {
    cleanupTooltip,
    dismissInsightTooltips,
    ensureTooltip,
    hideTooltip,
    pinTooltip,
    showTooltip,
} from './useInsightTooltip'

describe('useInsightTooltip', () => {
    const hoverEl = (): HTMLElement => document.getElementById('InsightTooltipWrapper-hover') as HTMLElement
    const pinnedEl = (): HTMLElement => document.getElementById('InsightTooltipWrapper-pinned') as HTMLElement

    function showFor(id: string): void {
        act(() => {
            const [root] = ensureTooltip(id)
            root.render(`tooltip for ${id}`)
        })
        showTooltip(id)
    }

    afterEach(() => {
        act(() => {
            dismissInsightTooltips()
        })
    })

    it('unlatches the pointer when an owner unmounts with the pointer on the tooltip', () => {
        jest.useFakeTimers()
        showFor('chart-a')
        // Only a mouseleave clears this latch, and an owner that unmounts under the pointer
        // never sends one — leaving every later hide blocked.
        hoverEl().dispatchEvent(new MouseEvent('mouseenter'))
        act(() => {
            cleanupTooltip('chart-a')
        })

        showFor('chart-b')
        act(() => {
            hideTooltip('chart-b')
            jest.runOnlyPendingTimers()
        })

        expect(hoverEl().style.opacity).toBe('0')
        jest.useRealTimers()
    })

    it('hides a hover tooltip owned by another chart when any chart unmounts', () => {
        showFor('chart-a')

        act(() => {
            cleanupTooltip('chart-b')
        })

        expect(hoverEl().style.opacity).toBe('0')
    })

    it('keeps a pinned tooltip when an unrelated chart unmounts', () => {
        showFor('chart-a')
        act(() => {
            pinTooltip('chart-a')
        })

        act(() => {
            cleanupTooltip('chart-b')
        })

        expect(pinnedEl().style.opacity).toBe('1')
    })

    it('hides both surfaces on navigation, whoever owns them', () => {
        showFor('chart-a')
        act(() => {
            pinTooltip('chart-a')
        })
        showFor('chart-b')

        act(() => {
            dismissInsightTooltips()
        })

        expect(hoverEl().style.opacity).toBe('0')
        expect(pinnedEl().style.opacity).toBe('0')
    })
})
