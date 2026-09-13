import { render } from '@testing-library/react'

import { getMarkdownNotebookDefaultRegistry } from './registry'
import { NotebookComponentBlockNode } from './types'

describe('markdown notebook registry', () => {
    function renderEmbed(src: string): HTMLIFrameElement | null {
        const definition = getMarkdownNotebookDefaultRegistry().components.Embed
        const node: NotebookComponentBlockNode = {
            id: 'embed-1',
            type: 'component',
            tagName: 'Embed',
            props: { src, title: 'Embedded content' },
        }
        const { container } = render(
            <definition.ViewComponent node={node} mode="view" updateProps={() => {}} deleteNode={() => {}} />
        )
        return container.querySelector('iframe')
    }

    it.each([
        'javascript:parent.document.body.remove()',
        'data:text/html,<script>parent.document.body.remove()</script>',
        'about:blank',
    ])('renders no iframe for the %s embed target', (src) => {
        expect(renderEmbed(src)).toBeNull()
    })

    it('withholds allow-same-origin from an embed on our own origin', () => {
        // With it, the framed page can script this document and remove its own sandbox.
        expect(renderEmbed(`${window.location.origin}/embedded/abc`)?.getAttribute('sandbox')).toEqual('allow-scripts')
    })

    it('keeps allow-same-origin for a third-party embed', () => {
        expect(renderEmbed('https://example.com/embed')?.getAttribute('sandbox')).toEqual(
            'allow-scripts allow-same-origin'
        )
    })
})
