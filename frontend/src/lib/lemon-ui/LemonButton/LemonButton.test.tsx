import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonButton } from './LemonButton'

describe('LemonButton', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so `screen` stays isolated.
    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            desc: 'submit (disabledReason)',
            htmlType: 'submit' as const,
            extraProps: { disabledReason: 'Not allowed' as const },
            handler: 'onSubmit' as const,
            label: 'Save',
        },
        {
            desc: 'submit (disabled)',
            htmlType: 'submit' as const,
            extraProps: { disabled: true as const },
            handler: 'onSubmit' as const,
            label: 'Save',
        },
        {
            desc: 'submit (loading)',
            htmlType: 'submit' as const,
            extraProps: { loading: true as const },
            handler: 'onSubmit' as const,
            label: 'Save',
        },
        {
            desc: 'reset (disabledReason)',
            htmlType: 'reset' as const,
            extraProps: { disabledReason: 'Not allowed' as const },
            handler: 'onReset' as const,
            label: 'Reset',
        },
    ])('click does not trigger form $handler — $desc', async ({ htmlType, extraProps, handler, label }) => {
        const user = userEvent.setup()
        const fn = jest.fn()

        render(
            <form {...(handler === 'onSubmit' ? { onSubmit: fn } : { onReset: fn })}>
                <LemonButton htmlType={htmlType} {...extraProps}>
                    {label}
                </LemonButton>
            </form>
        )

        await user.click(screen.getByRole('button', { name: label }))

        expect(fn).not.toHaveBeenCalled()
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
})
