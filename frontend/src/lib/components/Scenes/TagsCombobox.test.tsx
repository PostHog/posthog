import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { TagsCombobox } from './TagsCombobox'

function StatefulTags({ initialTags }: { initialTags: string[] }): JSX.Element {
    const [tags, setTags] = useState(initialTags)
    return <TagsCombobox value={tags} onChange={setTags} placeholder="Add tags..." />
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
    ])('keeps the tags when Escape is pressed %s', async (_, firstKeystrokes, expectedTags) => {
        render(<StatefulTags initialTags={['existing']} />)
        await userEvent.click(screen.getByPlaceholderText('Add tags...'))
        await userEvent.keyboard(firstKeystrokes)
        await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument())

        await userEvent.keyboard('{Escape}')
        await act(async () => {})

        expect(chipTitles()).toEqual(expectedTags)
    })
})
