import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FilterPickerToken } from './FilterPicker.types'
import { FilterPickerTokenPill } from './FilterPickerTokenPill'

const token: FilterPickerToken = {
    id: 'status-active',
    parts: [
        { kind: 'property', label: 'Status' },
        { kind: 'operator', label: '=' },
        { kind: 'value', label: 'Active' },
    ],
}

describe('FilterPickerTokenPill', () => {
    afterEach(() => {
        cleanup()
    })

    it('uses separate accessible edit and remove controls', async () => {
        const onEdit = jest.fn()
        const onRemove = jest.fn()

        render(<FilterPickerTokenPill token={token} onEdit={onEdit} onRemove={onRemove} />)

        await userEvent.click(screen.getByRole('button', { name: 'Edit filter: Status = Active' }))
        expect(onEdit).toHaveBeenCalledTimes(1)
        expect(onRemove).not.toHaveBeenCalled()

        await userEvent.click(screen.getByRole('button', { name: 'Remove filter: Status = Active' }))
        expect(onRemove).toHaveBeenCalledTimes(1)
        expect(onEdit).toHaveBeenCalledTimes(1)
    })

    it('does not render a remove control when the token is not removable', () => {
        render(<FilterPickerTokenPill token={{ ...token, removable: false }} onRemove={jest.fn()} />)

        expect(screen.getByRole('button', { name: 'Filter: Status = Active' })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Remove filter: Status = Active' })).not.toBeInTheDocument()
    })
})
