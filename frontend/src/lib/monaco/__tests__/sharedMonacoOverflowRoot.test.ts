import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { _resetSharedMonacoOverflowRootForTests, sharedMonacoOverflowRoot } from 'lib/monaco/sharedMonacoOverflowRoot'

describe('sharedMonacoOverflowRoot', () => {
    afterEach(() => {
        _resetSharedMonacoOverflowRootForTests()
    })

    it('attaches exactly one [data-attr="monaco-overflow-root"] to body across many calls', () => {
        sharedMonacoOverflowRoot()
        sharedMonacoOverflowRoot()
        sharedMonacoOverflowRoot()

        expect(document.querySelectorAll('[data-attr="monaco-overflow-root"]')).toHaveLength(1)
    })

    it('returns the same element on subsequent calls', () => {
        const first = sharedMonacoOverflowRoot()
        const second = sharedMonacoOverflowRoot()

        expect(first).not.toBeUndefined()
        expect(first).toBe(second)
        expect(first?.parentNode).toBe(document.body)
    })

    it('carries the click-outside-block class so suggestion clicks do not dismiss the host popover', () => {
        // Suggestion/hover widgets portal here at body level; without the block class a click on a
        // SQL-expression autocomplete would read as an outside click and close the TaxonomicFilter.
        const root = sharedMonacoOverflowRoot()

        expect(root?.classList.contains(CLICK_OUTSIDE_BLOCK_CLASS)).toBe(true)
    })

    it('reattaches if the singleton was removed externally and stays unique on body', () => {
        const first = sharedMonacoOverflowRoot()
        first?.remove()

        const second = sharedMonacoOverflowRoot()

        expect(second).not.toBeUndefined()
        expect(second).not.toBe(first)
        expect(document.querySelectorAll('[data-attr="monaco-overflow-root"]')).toHaveLength(1)
    })
})
