import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { DateVariable } from '../../types'
import { VariableInput } from './Variables'

const dateVariable: DateVariable = {
    id: 'date-variable',
    name: 'start',
    code_name: 'start',
    type: 'Date',
    default_value: '2026-03-31',
}

describe('VariableInput', () => {
    beforeEach(() => {
        window.HTMLElement.prototype.scrollIntoView = jest.fn()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const renderInput = (variable: DateVariable): { onChange: jest.Mock; closePopover: jest.Mock } => {
        const onChange = jest.fn()
        const closePopover = jest.fn()

        render(
            <Provider>
                <VariableInput
                    variable={variable}
                    showEditingUI={false}
                    onChange={onChange}
                    closePopover={closePopover}
                />
            </Provider>
        )

        return { onChange, closePopover }
    }

    it('commits a fixed date from the calendar Apply button', async () => {
        const { onChange, closePopover } = renderInput(dateVariable)

        expect(screen.queryByText('Update')).not.toBeInTheDocument()

        await userEvent.click(screen.getAllByText('15')[0])
        await userEvent.click(screen.getByText('Apply'))

        expect(onChange).toHaveBeenCalledWith('date-variable', '2026-03-15', false)
        expect(closePopover).toHaveBeenCalled()
    })

    it('does not commit when switching between fixed and relative dates', async () => {
        const { onChange, closePopover } = renderInput({ ...dateVariable, default_value: '-7d' })

        await userEvent.click(screen.getByText('Fixed date'))

        expect(onChange).not.toHaveBeenCalled()
        expect(closePopover).not.toHaveBeenCalled()
    })

    it('keeps the Update button for relative dates, which have no Apply of their own', async () => {
        const { onChange, closePopover } = renderInput({ ...dateVariable, default_value: '-7d' })

        await userEvent.click(screen.getByText('Update'))

        expect(onChange).toHaveBeenCalledWith('date-variable', '-7d', false)
        expect(closePopover).toHaveBeenCalled()
    })
})
