import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonButton } from './LemonButton'

describe('LemonButton', () => {
    afterEach(() => {
        cleanup()
    })

    test('does not submit form when disabledReason is set', async () => {
        const onSubmit = jest.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault())

        render(
            <form onSubmit={onSubmit}>
                <LemonButton htmlType="submit" disabledReason="Fill required fields">
                    Save
                </LemonButton>
            </form>
        )

        await userEvent.click(screen.getByRole('button', { name: 'Save' }))

        expect(onSubmit).not.toHaveBeenCalled()
    })

    test('submits form when button is enabled', async () => {
        const onSubmit = jest.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault())

        render(
            <form onSubmit={onSubmit}>
                <LemonButton htmlType="submit">Save</LemonButton>
            </form>
        )

        await userEvent.click(screen.getByRole('button', { name: 'Save' }))

        expect(onSubmit).toHaveBeenCalledTimes(1)
    })
})
