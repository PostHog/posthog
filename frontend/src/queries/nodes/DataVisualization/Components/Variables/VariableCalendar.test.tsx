import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { VariableCalendar } from './VariableCalendar'

describe('VariableCalendar', () => {
    beforeEach(() => {
        window.HTMLElement.prototype.scrollIntoView = jest.fn()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps include time off when reopened with a saved date-only value', async () => {
        const updateVariable = jest.fn()
        const { unmount } = render(
            <Provider>
                <VariableCalendar value={dayjs('2026-03-31')} rawValue="2026-03-31" updateVariable={updateVariable} />
            </Provider>
        )

        await userEvent.click(screen.getAllByRole('button', { name: '15' })[0])
        await userEvent.click(screen.getByRole('button', { name: 'Apply' }))

        expect(updateVariable).toHaveBeenLastCalledWith('2026-03-15')

        unmount()
        updateVariable.mockClear()

        render(
            <Provider>
                <VariableCalendar value={dayjs('2026-03-31')} rawValue="2026-03-31" updateVariable={updateVariable} />
            </Provider>
        )

        await userEvent.click(screen.getAllByRole('button', { name: '16' })[0])
        await userEvent.click(screen.getByRole('button', { name: 'Apply' }))

        expect(updateVariable).toHaveBeenLastCalledWith('2026-03-16')
    })

    it('keeps include time on when reopened with a saved datetime value', async () => {
        const updateVariable = jest.fn()
        const { unmount } = render(
            <Provider>
                <VariableCalendar
                    value={dayjs('2026-03-31 09:30:00')}
                    rawValue="2026-03-31 09:30:00"
                    updateVariable={updateVariable}
                />
            </Provider>
        )

        await userEvent.click(screen.getAllByRole('button', { name: '15' })[0])
        await userEvent.click(screen.getByRole('button', { name: 'Apply' }))

        expect(updateVariable).toHaveBeenLastCalledWith(expect.stringMatching(/^2026-03-15 \d{2}:\d{2}:00$/))

        unmount()
        updateVariable.mockClear()

        render(
            <Provider>
                <VariableCalendar
                    value={dayjs('2026-03-31 09:30:00')}
                    rawValue="2026-03-31 09:30:00"
                    updateVariable={updateVariable}
                />
            </Provider>
        )

        await userEvent.click(screen.getAllByRole('button', { name: '16' })[0])
        await userEvent.click(screen.getByRole('button', { name: 'Apply' }))

        expect(updateVariable).toHaveBeenLastCalledWith(expect.stringMatching(/^2026-03-16 \d{2}:\d{2}:00$/))
    }, 10000)

    it('saves a date-only value when include time is off', async () => {
        const updateVariable = jest.fn()
        render(
            <Provider>
                <VariableCalendar value={dayjs('2026-03-31')} rawValue="2026-03-31" updateVariable={updateVariable} />
            </Provider>
        )

        await userEvent.click(screen.getByRole('button', { name: '15' }))
        await userEvent.click(screen.getByRole('button', { name: 'Apply' }))

        expect(updateVariable).toHaveBeenCalledWith('2026-03-15')
    })
})
