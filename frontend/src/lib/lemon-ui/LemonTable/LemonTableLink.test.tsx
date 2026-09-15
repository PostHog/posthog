import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { LemonTableLink } from './LemonTableLink'

describe('LemonTableLink', () => {
    it('invokes onClick when clicked, even without a `to` (e.g. to open a modal instead of navigating)', () => {
        const onClick = jest.fn()
        render(<LemonTableLink title="Some theme" onClick={onClick} />)

        fireEvent.click(screen.getByText('Some theme'))
        expect(onClick).toHaveBeenCalledTimes(1)
    })

    it('still navigates via `to` when provided, same as before', () => {
        render(<LemonTableLink title="Some page" to="/insights/1" />)

        const anchor = screen.getByText('Some page').closest('a')
        expect(anchor).not.toBeNull()
        expect(anchor?.getAttribute('href')).toContain('/insights/1')
    })

    it('renders plain, non-interactive content when neither `to` nor `onClick` is given', () => {
        render(<LemonTableLink title="Just a label" />)

        const title = screen.getByText('Just a label')
        expect(title.closest('a')).toBeNull()
        expect(title.closest('button')).toBeNull()
    })

    it('renders plain, non-interactive content when onClick is explicitly undefined (conditional handler pattern)', () => {
        // mirrors call sites like `onClick={row ? () => doThing(row.id) : undefined}`
        render(<LemonTableLink title="Default" onClick={undefined} />)

        const title = screen.getByText('Default')
        expect(title.closest('a')).toBeNull()
        expect(title.closest('button')).toBeNull()
    })
})
