import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { QuillMappingCombobox } from './QuillMappingCombobox'

const OPTIONS = [
    { key: 'utm_source', label: 'utm_source (String)' },
    { key: 'utm_medium', label: 'utm_medium (String)' },
]

function StatefulMapping(): JSX.Element {
    const [value, setValue] = useState<string | null>(null)
    return (
        <QuillMappingCombobox
            value={value}
            onChange={setValue}
            options={OPTIONS}
            placeholder="Pick a column"
            ariaLabel="Source column"
        />
    )
}

describe('QuillMappingCombobox', () => {
    afterEach(() => {
        cleanup()
    })

    it('does not offer the picked option label back as a custom value', async () => {
        render(<StatefulMapping />)
        const input = screen.getByLabelText('Source column')

        await userEvent.click(input)
        await userEvent.click(within(screen.getByRole('listbox')).getByText('utm_source (String)'))
        await userEvent.click(input)

        expect(input).toHaveValue('utm_source (String)')
        expect(screen.queryByText('Use "utm_source (String)"')).not.toBeInTheDocument()
    })
})
