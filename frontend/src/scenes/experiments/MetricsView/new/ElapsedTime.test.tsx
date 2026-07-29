import { act, render } from '@testing-library/react'

import { ElapsedTime } from './ElapsedTime'

/**
 * Models what Chrome's and Edge's in-page translation actually do to the DOM: every translatable
 * text node is replaced by a `<font>` element holding the translated text, and `translate="no"`
 * subtrees are left alone. React keeps pointing at the original node, so removing it later throws
 * `NotFoundError: Failed to execute 'removeChild' on 'Node'` (react#11538).
 */
function simulatePageTranslation(root: HTMLElement): void {
    const walk = (node: Node): void => {
        if (node.nodeType === Node.ELEMENT_NODE && (node as HTMLElement).getAttribute('translate') === 'no') {
            return
        }
        for (const child of Array.from(node.childNodes)) {
            if (child.nodeType === Node.TEXT_NODE && child.textContent?.trim()) {
                const translated = document.createElement('font')
                translated.textContent = `翻译:${child.textContent}`
                node.replaceChild(translated, child)
            } else {
                walk(child)
            }
        }
    }
    walk(root)
}

describe('ElapsedTime', () => {
    // Mirrors the TimeseriesModal call site, where the elapsed time is followed by a sibling text node.
    const Host = ({ startTime }: { startTime: string | null }): JSX.Element => (
        <div>
            <ElapsedTime startTime={startTime} /> elapsed
        </div>
    )

    it('survives a translated page when the recalculation finishes', () => {
        const { container, rerender } = render(<Host startTime="2026-07-29T00:00:00Z" />)
        simulatePageTranslation(container)

        // Dropping startTime unmounts the elapsed time, which is where React removes the node the
        // translation swapped out from under it.
        expect(() => act(() => rerender(<Host startTime={null} />))).not.toThrow()
    })
})
