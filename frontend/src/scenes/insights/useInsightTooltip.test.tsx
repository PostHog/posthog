import { renderHook } from '@testing-library/react'
import { act } from 'react'

import { __resetUseInsightTooltipForTests, useInsightTooltip } from './useInsightTooltip'

declare global {
    // eslint-disable-next-line no-var
    var IS_REACT_ACT_ENVIRONMENT: boolean
}

describe('useInsightTooltip', () => {
    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true
    })

    afterEach(() => {
        __resetUseInsightTooltipForTests()
    })

    it('lazily creates a single shared hover element on first getTooltip', () => {
        expect(document.getElementById('InsightTooltipWrapper-hover')).toBeNull()

        const { result } = renderHook(() => useInsightTooltip())
        const [root, element] = result.current.getTooltip()

        expect(element.id).toBe('InsightTooltipWrapper-hover')
        expect(document.getElementById('InsightTooltipWrapper-hover')).toBe(element)
        expect(root).not.toBeNull()
    })

    it('preserves the active tooltip render when a non-owning sibling unmounts', () => {
        const a = renderHook(() => useInsightTooltip())
        const b = renderHook(() => useInsightTooltip())

        const [aRoot] = a.result.current.getTooltip()
        act(() => {
            aRoot.render(<span>a-content</span>)
        })

        // B becomes the active owner from this point on
        const [bRoot] = b.result.current.getTooltip()
        act(() => {
            bRoot.render(<span>b-content</span>)
        })

        const tooltipEl = document.getElementById('InsightTooltipWrapper-hover')!
        expect(tooltipEl.textContent).toBe('b-content')

        // A unmounts — A is not the owner, cleanup must be a no-op
        act(() => {
            a.unmount()
        })

        expect(document.getElementById('InsightTooltipWrapper-hover')!.textContent).toBe('b-content')
    })

    it('drops renders from a caller that has lost ownership', () => {
        const a = renderHook(() => useInsightTooltip())
        const b = renderHook(() => useInsightTooltip())

        const [aRoot] = a.result.current.getTooltip()
        // B taking ownership invalidates A's wrapped Root for further renders
        b.result.current.getTooltip()

        // The hook intentionally console.errors when this happens; suppress for this test
        const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})

        act(() => {
            aRoot.render(<span>should-be-dropped</span>)
        })

        const tooltipEl = document.getElementById('InsightTooltipWrapper-hover')!
        expect(tooltipEl.textContent).toBe('')
        expect(errorSpy).toHaveBeenCalled()
        errorSpy.mockRestore()
    })

    it('clears the rendered tooltip when the owning consumer unmounts', () => {
        const { result, unmount } = renderHook(() => useInsightTooltip())
        const [root] = result.current.getTooltip()
        act(() => {
            root.render(<span>content</span>)
        })

        expect(document.getElementById('InsightTooltipWrapper-hover')!.textContent).toBe('content')

        act(() => {
            unmount()
        })

        // Element is parked in the DOM (so a future mount can reuse the Root) but content is cleared
        expect(document.getElementById('InsightTooltipWrapper-hover')).not.toBeNull()
        expect(document.getElementById('InsightTooltipWrapper-hover')!.textContent).toBe('')
    })
})
