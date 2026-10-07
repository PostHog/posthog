import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useActions, useValues } from 'kea'

import { NodeKind } from '~/queries/schema/schema-general'

import { Reload } from './Reload'

jest.mock('posthog-js')

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

describe('Reload', () => {
    const loadData = jest.fn()
    const cancelQuery = jest.fn()

    const renderReload = (responseLoading: boolean): void => {
        jest.mocked(useValues).mockReturnValue({
            responseLoading,
            query: { kind: NodeKind.HogQLQuery, query: 'select 1' },
            loadingStart: responseLoading ? performance.now() : null,
        })
        jest.mocked(useActions).mockReturnValue({ loadData, cancelQuery })
        render(<Reload />)
    }

    beforeEach(() => {
        jest.useFakeTimers()
        loadData.mockClear()
        cancelQuery.mockClear()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('ignores a fast second click and only offers cancel after the query runs for a while', async () => {
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
        renderReload(true)

        expect(screen.getByText('Reload')).toBeInTheDocument()
        await user.click(screen.getByText('Reload'))
        expect(cancelQuery).not.toHaveBeenCalled()

        act(() => {
            jest.advanceTimersByTime(1000)
        })

        await user.click(screen.getByText('Cancel'))
        expect(cancelQuery).toHaveBeenCalledTimes(1)
    })
})
