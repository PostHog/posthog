import { render } from '@testing-library/react'

import { parseMarkdownNotebook } from './markdown'
import { getMarkdownNotebookDefaultRegistry } from './registry'

describe('markdown notebook embed rendering', () => {
    it.each([
        ['https://example.com/embed', 'https://example.com/embed'],
        ['http://localhost:8000/embed', 'http://localhost:8000/embed'],
        ['  HTTPS://example.com/embed  ', 'HTTPS://example.com/embed'],
        [`${window.location.origin}/embed`, `${window.location.origin}/embed`],
        ['javascript:void(0)', null],
        ['data:text/html,example', null],
        ['about:blank', null],
        ['//example.com/embed', null],
        ['/embed', null],
        ['https://', null],
        ['https://[invalid', null],
        ['https://example.com/a b', null],
        ['java\nscript:void(0)', null],
        ['', null],
    ])('validates and isolates the embed source %s', (src, expectedSrc) => {
        const document = parseMarkdownNotebook(`<Embed src=${JSON.stringify(src)} title="Example" />`)
        const node = document.nodes[0]
        if (node.type !== 'component') {
            throw new Error('Expected an embed component')
        }
        const { ViewComponent } = getMarkdownNotebookDefaultRegistry().components.Embed
        const { container } = render(
            <ViewComponent node={node} mode="view" updateProps={jest.fn()} deleteNode={jest.fn()} />
        )
        const iframe = container.querySelector('iframe')
        if (expectedSrc === null) {
            expect(iframe).toBeNull()
        } else {
            expect(iframe?.getAttribute('src')).toBe(expectedSrc)
            expect(iframe?.getAttribute('sandbox')).toBe('allow-scripts')
        }
    })
})
