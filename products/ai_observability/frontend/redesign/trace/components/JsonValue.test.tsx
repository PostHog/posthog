import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { JsonValue } from './JsonValue'

describe('JsonValue', () => {
    afterEach(cleanup)

    const text = 'Process refunds promptly'

    it.each([
        ['a top-level string', text],
        ['a string in an object', { message: text }],
    ])('shows %s in full when expanded', (_, value) => {
        const view = render(<JsonValue value={value} collapseStringsAfterLength={12} />)

        expect(view.getByText('Process refu…')).toBeVisible()
        fireEvent.click(view.getByText('Show more'))
        expect(view.getByText(text)).toBeVisible()
        fireEvent.click(view.getByText('Show less'))
        expect(view.getByText('Process refu…')).toBeVisible()
    })
})
