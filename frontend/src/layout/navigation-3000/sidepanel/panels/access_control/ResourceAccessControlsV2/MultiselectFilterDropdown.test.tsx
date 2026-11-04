import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { MultiSelectFilterDropdown } from './MultiselectFilterDropdown'

function FilterHarness(): JSX.Element {
    const [values, setValues] = useState<string[]>([])
    return (
        <MultiSelectFilterDropdown
            title="Access"
            placeholder="Filter by access…"
            options={[
                { key: 'admin', label: 'Admin' },
                { key: 'member', label: 'Member' },
            ]}
            values={values}
            setValues={setValues}
        />
    )
}

describe('MultiSelectFilterDropdown', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['the option label', (option: HTMLElement) => within(option).getByText('Admin')],
        ['the checkbox', (option: HTMLElement) => option.querySelector('label')!],
    ])('selects and clears an option when the click lands on %s', async (_, getTarget) => {
        const user = userEvent.setup()
        render(<FilterHarness />)
        const option = screen.getByText('Admin').closest('button')!

        await user.click(getTarget(option))
        expect(option).toHaveAttribute('aria-checked', 'true')

        await user.click(getTarget(option))
        expect(option).toHaveAttribute('aria-checked', 'false')
    })
})
