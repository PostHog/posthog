import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { dateMapping } from 'lib/utils'

import { initKeaTests } from '~/test/init'

import { DateFilter } from './DateFilter'

describe('DateFilter', () => {
    let onChange = jest.fn()
    beforeEach(() => {
        initKeaTests()
        onChange = jest.fn()
        render(
            <Provider>
                <DateFilter onChange={onChange} dateOptions={dateMapping} />
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
    })

    it('Can set the date filter and show the right grouping interval', async () => {
        const dateFilter = screen.getByTestId('date-filter')
        userEvent.click(dateFilter)

        const yesterdayButton = screen.getByText('Yesterday')
        userEvent.click(yesterdayButton)

        expect(onChange).toHaveBeenCalledWith('-1dStart', '-1dEnd', false)
    })

    it('can set a custom rolling date range', async () => {
        const dateFilter = screen.getByTestId('date-filter')
        userEvent.click(dateFilter)

        const rollingInput = screen.getByTestId('rolling-date-range-input')
        userEvent.clear(rollingInput)
        userEvent.type(rollingInput, '5')
        userEvent.keyboard('{Enter}')

        const dateOptionsSelector = screen.getByTestId('rolling-date-range-date-options-selector')
        userEvent.click(dateOptionsSelector)

        const rollingLabel = screen.getByTestId('rolling-date-range-filter')
        expect(rollingLabel).toHaveTextContent('In the last')
        userEvent.click(rollingLabel)

        await waitFor(() => expect(onChange).toHaveBeenCalledWith('-5d', '', false))
    })
})
