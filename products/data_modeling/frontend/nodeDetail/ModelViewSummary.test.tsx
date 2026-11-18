import { render } from '@testing-library/react'

import { ModelViewSummary } from './ModelViewSummary'

describe('ModelViewSummary', () => {
    it('updates the downstream count after a translation extension replaces its text nodes', () => {
        const { container, rerender } = render(<ModelViewSummary downstreamCount={3} lineageUrl="#lineage" />)
        const link = container.querySelector('a')!
        expect(link.textContent).toBe('3 models')
        const walker = document.createTreeWalker(link, NodeFilter.SHOW_TEXT)
        const textNodes: Node[] = []
        while (walker.nextNode()) {
            textNodes.push(walker.currentNode)
        }
        for (const text of textNodes) {
            const translated = document.createElement('font')
            translated.textContent = text.textContent
            text.parentNode!.replaceChild(translated, text)
        }

        rerender(<ModelViewSummary downstreamCount={1} lineageUrl="#lineage" />)

        expect(container.querySelector('a')!.textContent).toBe('1 model')
    })
})
