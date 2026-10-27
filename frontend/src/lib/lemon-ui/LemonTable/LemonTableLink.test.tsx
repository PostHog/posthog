import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonTableLink } from './LemonTableLink'

describe('LemonTableLink', () => {
    afterEach(cleanup)

    it('renders a button that calls onClick when there is no to', () => {
        const onClick = jest.fn()
        render(<LemonTableLink title="Brand colors" onClick={onClick} />)

        fireEvent.click(screen.getByRole('button'))

        expect(onClick).toHaveBeenCalledTimes(1)
    })

    it('renders plain text when there is no to and no onClick', () => {
        render(<LemonTableLink title="Brand colors" />)

        expect(screen.getByText('Brand colors')).toBeInTheDocument()
        expect(screen.queryByRole('button')).not.toBeInTheDocument()
        expect(screen.queryByRole('link')).not.toBeInTheDocument()
    })
})
