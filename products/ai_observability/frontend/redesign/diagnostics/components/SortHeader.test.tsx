import { cleanup, fireEvent, render } from '@testing-library/react'

import { SortHeader } from './SortHeader'

describe('SortHeader', () => {
    afterEach(cleanup)

    it.each([
        ['sorts by a column the list is not sorted by', false, 1],
        ['does nothing for the column the list is already sorted by', true, 0],
    ])('%s', (_name, active, calls) => {
        const onSort = jest.fn()
        const { getByText } = render(
            <SortHeader label="Occurrences" active={active} onSort={onSort} data-attr="errors-list-order-occurrences" />
        )

        fireEvent.click(getByText('Occurrences'))

        expect(onSort).toHaveBeenCalledTimes(calls)
    })
})
