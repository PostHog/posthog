import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { QuillConditionSetDescription } from './QuillConditionSetDescription'

describe('QuillConditionSetDescription', () => {
    afterEach(() => {
        cleanup()
    })

    it('drops an unsaved draft when the description is reset from outside', () => {
        const onSave = jest.fn()
        const { rerender } = render(
            <QuillConditionSetDescription description="Original" dataAttr="description" onSave={onSave} />
        )
        fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Discarded edit' } })

        rerender(<QuillConditionSetDescription description="Reset" dataAttr="description" onSave={onSave} />)
        fireEvent.blur(screen.getByLabelText('Description'))

        expect(screen.getByLabelText('Description')).toHaveValue('Reset')
        expect(onSave).not.toHaveBeenCalled()
    })
})
