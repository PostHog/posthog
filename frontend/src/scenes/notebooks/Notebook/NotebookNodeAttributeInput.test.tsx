import { act, cleanup, fireEvent, render, within } from '@testing-library/react'

import { NOTEBOOK_NODE_ATTRIBUTE_COMMIT_DEBOUNCE_MS, NotebookNodeAttributeInput } from './NotebookNodeAttributeInput'

const UUID = '0198a4c2-8b3d-7e50-b4a1-2f9c6d8e0a1b'

describe('NotebookNodeAttributeInput', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    const setup = (
        expectsUUID: boolean
    ): {
        input: HTMLElement
        container: HTMLElement
        onCommit: jest.Mock
        type: (value: string) => void
        settle: () => void
    } => {
        const onCommit = jest.fn()
        const { container } = render(
            <NotebookNodeAttributeInput label="Person UUID" value="" expectsUUID={expectsUUID} onCommit={onCommit} />
        )
        const input = within(container).getByRole('textbox')
        return {
            input,
            container,
            onCommit,
            type: (value: string) => fireEvent.change(input, { target: { value } }),
            settle: () =>
                act(() => {
                    jest.advanceTimersByTime(NOTEBOOK_NODE_ATTRIBUTE_COMMIT_DEBOUNCE_MS)
                }),
        }
    }

    it('commits a UUID once it is complete, not once per keystroke', () => {
        const { onCommit, type, settle } = setup(true)

        for (let length = 1; length <= UUID.length; length++) {
            type(UUID.slice(0, length))
            settle()
        }

        expect(onCommit).toHaveBeenCalledTimes(1)
        expect(onCommit).toHaveBeenCalledWith(UUID)
    })

    it('warns instead of committing while the UUID is partial', () => {
        const { container, onCommit, type, settle } = setup(true)

        type('0198a4c2-8b3d')
        settle()

        expect(onCommit).not.toHaveBeenCalled()
        expect(within(container).queryByText(/Enter a full UUID/)).not.toBeNull()
    })

    it('accepts a UUID pasted with surrounding whitespace', () => {
        const { onCommit, type, settle } = setup(true)

        type(` ${UUID}\n`)
        settle()

        expect(onCommit).toHaveBeenCalledWith(UUID)
    })

    it('debounces a burst of keystrokes into a single commit for non-UUID attributes', () => {
        const { onCommit, type, settle } = setup(false)

        for (const value of ['a', 'ac', 'acm', 'acme']) {
            type(value)
        }
        settle()

        expect(onCommit).toHaveBeenCalledTimes(1)
        expect(onCommit).toHaveBeenCalledWith('acme')
    })

    it('commits on blur without waiting for the debounce', () => {
        const { input, onCommit, type } = setup(false)

        type('acme')
        fireEvent.blur(input)

        expect(onCommit).toHaveBeenCalledWith('acme')
    })
})
