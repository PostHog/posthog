import { render, screen } from '@testing-library/react'

import { ModelViewSummary } from './ModelViewSummary'

describe('ModelViewSummary', () => {
    it('updates the downstream count after a translation extension replaces its text nodes', () => {
        const { rerender } = render(<ModelViewSummary downstreamCount={3} lineageUrl="#lineage" />)
        const link = screen.getByRole('link', { name: '3 models' })
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

        expect(screen.getByRole('link', { name: '1 model' }).textContent).toBe('1 model')
    })
})
