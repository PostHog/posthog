import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KeyboardEvent, useState } from 'react'

import { TagsCombobox } from './TagsCombobox'

function StatefulTags({
    initialTags,
    onParentKeyDown,
}: {
    initialTags: string[]
    onParentKeyDown: (event: KeyboardEvent) => void
}): JSX.Element {
    const [tags, setTags] = useState(initialTags)
    return (
        <div onKeyDown={onParentKeyDown}>
            <TagsCombobox value={tags} onChange={setTags} placeholder="Add tags..." />
        </div>
    )
}

function chipTitles(): string[] {
    return Array.from(document.querySelectorAll('[data-slot="combobox-chip"]')).map(
        (chip) => chip.getAttribute('title') ?? ''
    )
}

describe('TagsCombobox', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['after adding a tag', 'new-tag{Enter}', ['existing', 'new-tag']],
        ['after closing the list', '{Escape}', ['existing']],
    ])(
        'keeps the tags and lets the parent close when Escape is pressed %s',
        async (_, firstKeystrokes, expectedTags) => {
            const onParentKeyDown = jest.fn()
            render(<StatefulTags initialTags={['existing']} onParentKeyDown={onParentKeyDown} />)
            await userEvent.click(screen.getByPlaceholderText('Add tags...'))
            await userEvent.keyboard(firstKeystrokes)
            await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument())
            onParentKeyDown.mockClear()

            await userEvent.keyboard('{Escape}')
            await act(async () => {})

            expect(chipTitles()).toEqual(expectedTags)
            expect(onParentKeyDown).toHaveBeenCalledWith(expect.objectContaining({ key: 'Escape' }))
        }
    )
})
