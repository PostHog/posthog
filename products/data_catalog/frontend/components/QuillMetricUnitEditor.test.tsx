import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { QuillMetricUnitEditor } from './QuillMetricUnitEditor'

describe('QuillMetricUnitEditor', () => {
    afterEach(cleanup)

    it('keeps a unit edit made while another metric update is saving and saves it once that finishes', () => {
        const onSave = jest.fn()
        const { rerender } = render(<QuillMetricUnitEditor unit="users" saving={false} onSave={onSave} />)

        fireEvent.click(screen.getByText('users'))
        const input = screen.getByLabelText('Unit')
        fireEvent.change(input, { target: { value: 'accounts' } })

        rerender(<QuillMetricUnitEditor unit="users" saving onSave={onSave} />)
        fireEvent.keyDown(input, { key: 'Enter' })
        expect(onSave).not.toHaveBeenCalled()
        expect(screen.getByLabelText('Unit')).toHaveValue('accounts')

        rerender(<QuillMetricUnitEditor unit="users" saving={false} onSave={onSave} />)
        fireEvent.keyDown(screen.getByLabelText('Unit'), { key: 'Enter' })
        expect(onSave).toHaveBeenCalledWith('accounts')
    })
})
