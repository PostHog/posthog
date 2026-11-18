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

    test('shows a value too wide for the tree as text', () => {
        const src = Object.fromEntries(Array.from({ length: 3000 }, (_, index) => [`field_${index}`, index]))
        const { container } = render(<JsonTree src={src} />)

        expect(container.querySelector('.react-json-view')).toBeNull()
        expect(container.querySelector('pre')?.textContent).toContain('field_2999')
    })
})
