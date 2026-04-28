import { renderHook } from '@testing-library/react'
import { act } from 'react'

import { __resetSharedBillingTooltipForTests, useBillingTooltip } from './useBillingTooltip'

declare global {
    // eslint-disable-next-line no-var
    var IS_REACT_ACT_ENVIRONMENT: boolean
}

describe('useBillingTooltip', () => {
    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true
    })

    afterEach(() => {
        __resetSharedBillingTooltipForTests()
    })

    it('lazily creates a single shared tooltip element on first ensure', () => {
        expect(document.getElementById('BillingTooltipWrapper')).toBeNull()

        const { result } = renderHook(() => useBillingTooltip())
        const [root, element] = result.current.ensureBillingTooltip()

        expect(element.id).toBe('BillingTooltipWrapper')
        expect(document.getElementById('BillingTooltipWrapper')).toBe(element)
        expect(root).not.toBeNull()

        const [secondRoot, secondElement] = result.current.ensureBillingTooltip()
        expect(secondElement).toBe(element)
        expect(secondRoot).toBe(root)
    })

    it('preserves the rendered tooltip when a sibling instance unmounts', () => {
        const a = renderHook(() => useBillingTooltip())
        const b = renderHook(() => useBillingTooltip())

        const [aRoot] = a.result.current.ensureBillingTooltip()
        act(() => {
            aRoot.render(<span data-testid="tooltip-content">a-content</span>)
        })

        const [bRoot] = b.result.current.ensureBillingTooltip()
        act(() => {
            bRoot.render(<span data-testid="tooltip-content">b-content</span>)
        })

        const tooltipEl = document.getElementById('BillingTooltipWrapper')
        expect(tooltipEl).not.toBeNull()
        expect(tooltipEl!.textContent).toBe('b-content')

        act(() => {
            a.unmount()
        })

        // Sibling unmount must not wipe the active instance's tooltip
        expect(document.getElementById('BillingTooltipWrapper')!.textContent).toBe('b-content')

        act(() => {
            b.unmount()
        })

        // Last consumer unmount clears the tooltip content
        expect(document.getElementById('BillingTooltipWrapper')!.textContent).toBe('')
    })

    it('keeps the shared element parked in the DOM after the last consumer unmounts so it can be reused', () => {
        const { result, unmount } = renderHook(() => useBillingTooltip())
        const [root] = result.current.ensureBillingTooltip()
        act(() => {
            root.render(<span>content</span>)
        })

        expect(document.getElementById('BillingTooltipWrapper')!.textContent).toBe('content')

        act(() => {
            unmount()
        })

        // Element stays attached so the next mount short-circuits createRoot, avoiding the
        // double-createRoot leak the original PR fixes.
        expect(document.getElementById('BillingTooltipWrapper')).not.toBeNull()
        expect(document.getElementById('BillingTooltipWrapper')!.textContent).toBe('')

        const next = renderHook(() => useBillingTooltip())
        const [nextRoot, nextEl] = next.result.current.ensureBillingTooltip()
        expect(nextEl).toBe(document.getElementById('BillingTooltipWrapper'))
        act(() => {
            nextRoot.render(<span>fresh</span>)
        })
        expect(document.getElementById('BillingTooltipWrapper')!.textContent).toBe('fresh')

        act(() => {
            next.unmount()
        })
    })
})
