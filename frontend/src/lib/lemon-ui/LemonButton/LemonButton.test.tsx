import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonButton } from './LemonButton'

describe('LemonButton', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so `screen` stays isolated.
    afterEach(() => {
        cleanup()
    })

    it('does not submit a parent form when disabledReason is set (htmlType submit)', async () => {
        const user = userEvent.setup()
        const onSubmit = jest.fn()

        render(
            <form onSubmit={onSubmit}>
                <LemonButton htmlType="submit" disabledReason="Not allowed">
                    Save
                </LemonButton>
            </form>
        )

        await user.click(screen.getByRole('button', { name: 'Save' }))

        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('does not submit a parent form when disabled is set (htmlType submit)', async () => {
        const user = userEvent.setup()
        const onSubmit = jest.fn()

        render(
            <form onSubmit={onSubmit}>
                <LemonButton htmlType="submit" disabled>
                    Save
                </LemonButton>
            </form>
        )

        await user.click(screen.getByRole('button', { name: 'Save' }))

        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('does not fire onClick when disabledReason is set', async () => {
        const user = userEvent.setup()
        const onClick = jest.fn()

        render(
            <LemonButton disabledReason="Nope" onClick={onClick}>
                Go
            </LemonButton>
        )

        await user.click(screen.getByRole('button', { name: 'Go' }))

        expect(onClick).not.toHaveBeenCalled()
    })

    it('keeps htmlType submit in the DOM when disabledReason is set', () => {
        render(
            <LemonButton htmlType="submit" disabledReason="Nope">
                Save
            </LemonButton>
        )

        expect(screen.getByRole('button')).toHaveAttribute('type', 'submit')
    })

    it('does not implicitly submit the form (Enter in a field) when submit button has disabledReason', async () => {
        const user = userEvent.setup()
        const onSubmit = jest.fn()

        render(
            <form onSubmit={onSubmit}>
                <label htmlFor="implicit-submit-field">Field</label>
                <input id="implicit-submit-field" type="text" name="q" defaultValue="hello" />
                <LemonButton htmlType="submit" disabledReason="Not allowed">
                    Save
                </LemonButton>
            </form>
        )

        const input = screen.getByRole('textbox', { name: 'Field' })
        input.focus()
        expect(input).toHaveFocus()
        await user.keyboard('{Enter}')

        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('does not reset a parent form when disabledReason is set (htmlType reset)', async () => {
        const user = userEvent.setup()
        const onReset = jest.fn()

        render(
            <form onReset={onReset}>
                <LemonButton htmlType="reset" disabledReason="Not allowed">
                    Reset
                </LemonButton>
            </form>
        )

        await user.click(screen.getByRole('button', { name: 'Reset' }))

        expect(onReset).not.toHaveBeenCalled()
    })

    it('still submits when enabled (htmlType submit)', async () => {
        const user = userEvent.setup()
        const onSubmit = jest.fn((e) => e.preventDefault())

        render(
            <form onSubmit={onSubmit}>
                <LemonButton htmlType="submit">Save</LemonButton>
            </form>
        )

        await user.click(screen.getByRole('button', { name: 'Save' }))

        expect(onSubmit).toHaveBeenCalledTimes(1)
    })

    it('does not submit a parent form when loading is true (htmlType submit)', async () => {
        const user = userEvent.setup()
        const onSubmit = jest.fn()

        render(
            <form onSubmit={onSubmit}>
                <LemonButton htmlType="submit" loading>
                    Save
                </LemonButton>
            </form>
        )

        await user.click(screen.getByRole('button', { name: 'Save' }))

        expect(onSubmit).not.toHaveBeenCalled()
    })
})
