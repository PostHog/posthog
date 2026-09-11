import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { columnValueFilter } from './columnValueFilter'

describe('columnValueFilter', () => {
    afterEach(() => cleanup())

    const options = [
        { value: 'owner', label: 'Owner' },
        { value: 'admin', label: 'Admin' },
        { value: 'member', label: 'Member' },
    ]

    it('reports the selection count and toggles values in option order', async () => {
        const onChange = jest.fn()
        const column = columnValueFilter<Record<string, any>, string>({ options, selected: ['member'], onChange })

        expect(column.moreFilterCount).toBe(1)
        render(<>{column.more}</>)

        await userEvent.click(screen.getByText('Owner'))
        // Owner is listed before Member, so it lands first regardless of click order.
        expect(onChange).toHaveBeenLastCalledWith(['owner', 'member'])

        await userEvent.click(screen.getByText('Member'))
        expect(onChange).toHaveBeenLastCalledWith([])
    })
})
