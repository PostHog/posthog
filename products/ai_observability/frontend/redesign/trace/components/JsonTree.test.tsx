import { cleanup, render, waitFor } from '@testing-library/react'

import { JsonTree } from './JsonTree'

describe('JsonTree', () => {
    afterEach(cleanup)

    test.each([
        ['a match inside a grouped array', [...Array.from({ length: 150 }, (_, index) => index), 'needle']],
        ['a match past the string cut-off', { text: `${'a'.repeat(10500)} needle` }],
    ])('shows %s', async (_name, src) => {
        const { container } = render(<JsonTree src={src} highlightQuery="needle" />)

        await waitFor(() => expect(container.querySelector('.react-json-view')?.textContent).toContain('needle'))
    })

    test.each([
        [
            'a value too wide for the tree',
            Object.fromEntries(Array.from({ length: 3000 }, (_, index) => [`field_${index}`, index])),
            'field_2999',
            null,
        ],
        ['a closed array with too many groups', { level: { items: Array(250000).fill(0) } }, '"items"', null],
        [
            'a search match beside an unrelated string too long to open',
            { note: 'needle', prompt: 'a'.repeat(200000) },
            'needle',
            'needle',
        ],
    ])('shows %s as text', (_name, src, text, highlightQuery) => {
        const { container } = render(<JsonTree src={src} highlightQuery={highlightQuery} />)

        expect(container.querySelector('.react-json-view')).toBeNull()
        expect(container.querySelector('pre')?.textContent).toContain(text)
    })
})
