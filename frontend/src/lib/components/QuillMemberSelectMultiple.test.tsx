import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KeyboardEvent, useState } from 'react'

import { QuillMemberSelectMultiple } from './QuillMemberSelectMultiple'

const OPTIONS = [
    { key: 'alice', label: 'Alice' },
    { key: 'bob', label: 'Bob' },
]

function StatefulMembers({
    onChange,
    onParentKeyDown,
}: {
    onChange: (keys: string[]) => void
    onParentKeyDown: (event: KeyboardEvent) => void
}): JSX.Element {
    const [value, setValue] = useState(['alice', 'bob'])
    return (
        <div onKeyDown={onParentKeyDown}>
            <QuillMemberSelectMultiple
                options={OPTIONS}
                value={value}
                loading={false}
                onChange={(keys) => {
                    setValue(keys)
                    onChange(keys)
                }}
            />
        </div>
    )
}

function chipTitles(): string[] {
    return Array.from(document.querySelectorAll('[data-slot="combobox-chip"]')).map(
        (chip) => chip.getAttribute('title') ?? ''
    )
}

describe('QuillMemberSelectMultiple', () => {
    afterEach(() => {
        cleanup()
    })

    it('keeps the selected members and lets the parent close when Escape is pressed with the list closed', async () => {
        const onChange = jest.fn()
        const onParentKeyDown = jest.fn()
        render(<StatefulMembers onChange={onChange} onParentKeyDown={onParentKeyDown} />)

        await userEvent.click(screen.getByRole('combobox'))
        await userEvent.keyboard('{Escape}')
        await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument())
        onParentKeyDown.mockClear()

        await userEvent.keyboard('{Escape}')
        await act(async () => {})

        expect(chipTitles()).toEqual(['Alice', 'Bob'])
        expect(onChange).not.toHaveBeenCalled()
        expect(onParentKeyDown).toHaveBeenCalledWith(expect.objectContaining({ key: 'Escape' }))
    })
})
