import '@testing-library/jest-dom'

import { cleanup, render as rtlRender, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { PopoverOverlayContext } from '../Popover'
import { QuillTransitionContext } from '../QuillTransition/QuillTransitionContext'
import { LemonButton } from './LemonButton'

describe('LemonButton', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so `screen` stays isolated.
    afterEach(() => {
        cleanup()
    })

    it.each([
        { desc: 'transition off', quill: false, popoverLevel: -1, sideAction: false, expectQuill: false },
        { desc: 'transition on', quill: true, popoverLevel: -1, sideAction: false, expectQuill: true },
        {
            desc: 'transition on, inside a popover',
            quill: true,
            popoverLevel: 0,
            sideAction: false,
            expectQuill: false,
        },
        {
            desc: 'transition on, with a side action',
            quill: true,
            popoverLevel: -1,
            sideAction: true,
            expectQuill: false,
        },
    ])('renders quill only where supported — $desc', ({ quill, popoverLevel, sideAction, expectQuill }) => {
        rtlRender(
            <QuillTransitionContext.Provider value={quill}>
                <PopoverOverlayContext.Provider value={[true, popoverLevel]}>
                    <LemonButton sideAction={sideAction ? { icon: <span />, 'aria-label': 'More' } : undefined}>
                        Go
                    </LemonButton>
                </PopoverOverlayContext.Provider>
            </QuillTransitionContext.Provider>
        )

        const button = screen.getByRole('button', { name: 'Go' })
        expect(button.hasAttribute('data-quill')).toBe(expectQuill)
        expect(button.classList.contains('LemonButton')).toBe(!expectQuill)
    })

    describe.each([
        ['LemonUI', false],
        ['quill', true],
    ])('%s', (_name, quill) => {
        const render = (ui: React.ReactElement): void => {
            rtlRender(<QuillTransitionContext.Provider value={quill}>{ui}</QuillTransitionContext.Provider>)
        }

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

            await user.click(screen.getByRole('button'))

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

            await user.click(screen.getByRole('button'))

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

            const input = screen.getByLabelText('Field')
            input.focus()
            expect(input).toHaveFocus()
            await user.keyboard('{Enter}')

            expect(onSubmit).not.toHaveBeenCalled()
        })

        it('keeps the link role when the button navigates', () => {
            render(<LemonButton to="/insights">Insights</LemonButton>)

            expect(screen.getByRole('link', { name: 'Insights' })).toHaveAttribute('href', '/insights')
        })

        it('still submits when enabled (htmlType submit)', async () => {
            const user = userEvent.setup()
            const onSubmit = jest.fn((e) => e.preventDefault())

            render(
                <form onSubmit={onSubmit}>
                    <LemonButton htmlType="submit">Save</LemonButton>
                </form>
            )

            await user.click(screen.getByRole('button'))

            expect(onSubmit).toHaveBeenCalledTimes(1)
        })
    })
})
