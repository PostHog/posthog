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
        { desc: 'transition off', quill: false, popoverLevel: -1, props: {}, expectQuill: false, expectRow: false },
        { desc: 'transition on', quill: true, popoverLevel: -1, props: {}, expectQuill: true, expectRow: false },
        {
            desc: 'transition on, unpadded',
            quill: true,
            popoverLevel: -1,
            props: { noPadding: true },
            expectQuill: false,
            expectRow: false,
        },
        {
            desc: 'transition on, button inside a popover',
            quill: true,
            popoverLevel: 0,
            props: {},
            expectQuill: true,
            expectRow: false,
        },
        {
            desc: 'transition on, full-width row inside a popover',
            quill: true,
            popoverLevel: 0,
            props: { fullWidth: true },
            expectQuill: true,
            expectRow: true,
        },
        {
            desc: 'transition on, full-width outside a popover',
            quill: true,
            popoverLevel: -1,
            props: { fullWidth: true },
            expectQuill: true,
            expectRow: false,
        },
    ])('renders quill where supported — $desc', ({ quill, popoverLevel, props, expectQuill, expectRow }) => {
        rtlRender(
            <QuillTransitionContext.Provider value={quill}>
                <PopoverOverlayContext.Provider value={[true, popoverLevel]}>
                    <LemonButton {...props}>Go</LemonButton>
                </PopoverOverlayContext.Provider>
            </QuillTransitionContext.Provider>
        )

        const button = screen.getByRole('button')
        expect(button.hasAttribute('data-quill')).toBe(expectQuill)
        expect(button.classList.contains('LemonButton')).toBe(!expectQuill)
        expect(button.classList.contains('quill-button--size-row')).toBe(expectRow)
    })

    it.each([
        ['LemonUI', false],
        ['quill', true],
    ])('renders both halves of a split button with %s', (_name, quill) => {
        rtlRender(
            <QuillTransitionContext.Provider value={quill}>
                <LemonButton sideAction={{ icon: <span />, 'aria-label': 'More' }}>Go</LemonButton>
            </QuillTransitionContext.Provider>
        )

        for (const button of [screen.getByText('Go').closest('button'), screen.getByLabelText('More')]) {
            expect(button?.hasAttribute('data-quill')).toBe(quill)
        }
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

            expect(screen.getByRole('link')).toHaveAttribute('href', '/insights')
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
