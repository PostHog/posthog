import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KeyboardEvent, useState } from 'react'

import { TagsCombobox } from './TagsCombobox'

function StatefulTags({
    initialTags,
    onParentKeyDown = () => {},
    options,
    commitOnBlur,
}: {
    initialTags: string[]
    onParentKeyDown?: (event: KeyboardEvent) => void
    options?: string[]
    commitOnBlur?: boolean
}): JSX.Element {
    const [tags, setTags] = useState(initialTags)
    return (
        <div onKeyDown={onParentKeyDown}>
            <TagsCombobox
                value={tags}
                onChange={setTags}
                options={options}
                commitOnBlur={commitOnBlur}
                placeholder="Add tags..."
            />
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

    it.each([
        ['a click outside adds the typed value with commitOnBlur', true, ['click'], ['existing', 'typed']],
        ['Tab adds the typed value with commitOnBlur', true, ['{Tab}'], ['existing', 'typed']],
        ['Escape then a click outside drops the typed value', true, ['{Escape}', 'click'], ['existing']],
        ['a click outside drops the typed value by default', undefined, ['click'], ['existing']],
    ])('on leaving the input, %s', async (_, commitOnBlur, leaveSteps, expectedTags) => {
        render(
            <>
                <StatefulTags initialTags={['existing']} commitOnBlur={commitOnBlur} />
                <button type="button">Save</button>
            </>
        )
        await userEvent.click(screen.getByPlaceholderText('Add tags...'))
        await userEvent.keyboard('typed')

        for (const step of leaveSteps) {
            await (step === 'click' ? userEvent.click(screen.getByText('Save')) : userEvent.keyboard(step))
        }
        await act(async () => {})

        expect(chipTitles()).toEqual(expectedTags)
    })

    it('adds only the picked option, not the partly typed text, when commitOnBlur is on', async () => {
        render(<StatefulTags initialTags={[]} options={['HomeScreen']} commitOnBlur />)
        await userEvent.click(screen.getByPlaceholderText('Add tags...'))
        await userEvent.keyboard('Home')

        await userEvent.click(await screen.findByRole('option', { name: 'HomeScreen' }))
        await act(async () => {})

        expect(chipTitles()).toEqual(['HomeScreen'])
    })

    it('shows a value that starts like the create prefix as its own chip', () => {
        render(<TagsCombobox value={['__create__:paid', 'refunded']} onChange={jest.fn()} />)

        expect(screen.getByText('__create__:paid')).toBeInTheDocument()
        expect(screen.getByText('refunded')).toBeInTheDocument()
    })
})
