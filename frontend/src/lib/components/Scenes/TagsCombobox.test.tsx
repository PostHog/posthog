import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { TagsCombobox } from './TagsCombobox'

describe('TagsCombobox', () => {
    afterEach(cleanup)

    it('shows a value that starts like the create prefix as its own chip', () => {
        render(<TagsCombobox value={['__create__:paid', 'refunded']} onChange={jest.fn()} />)

        expect(screen.getByText('__create__:paid')).toBeInTheDocument()
        expect(screen.getByText('refunded')).toBeInTheDocument()
    })
})
