import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { ToastContainer, toast } from 'react-toastify'

import { GET_HELP_BUTTON, ToastContent, lemonToast } from './LemonToast'

describe('LemonToast', () => {
    const writeText = jest.fn((_text: string) => Promise.resolve())

    beforeEach(() => {
        jest.clearAllMocks()
        Object.assign(navigator, { clipboard: { writeText } })
    })

    // The copy button reads the rendered message out of the DOM, so it copies whatever sits inside the
    // message element. Widening that element to cover the action button would silently append "Get help"
    // to every error someone pastes elsewhere.
    it('copies the message without the action button label', async () => {
        const { container } = render(
            <ToastContent type="error" message="Load experiment failed" button={GET_HELP_BUTTON} />
        )

        fireEvent.click(container.querySelector('[data-attr="toast-copy-button"]')!)
        await act(async () => {})

        expect(writeText).toHaveBeenCalledWith('Load experiment failed')
    })

    it.each([
        ['error', true],
        ['warning', true],
        ['info', false],
        ['success', false],
    ] as const)('renders the copy button on a %s toast: %s', (type, expected) => {
        const { container } = render(<ToastContent type={type} message="A message" />)

        expect(!!container.querySelector('[data-attr="toast-copy-button"]')).toBe(expected)
    })

    // react-toastify's exit animation never finishes in jsdom, so a dismissed toast lingers in the
    // DOM. isActive() is its source of truth for whether a toast is still up, so assert on that.
    describe('dismissStaleErrors', () => {
        beforeEach(() => {
            jest.useFakeTimers()
        })

        afterEach(() => {
            act(() => {
                toast.dismiss()
            })
            cleanup()
            jest.useRealTimers()
        })

        it('dismisses an error left over from a previous page', async () => {
            render(<ToastContainer autoClose={false} />)
            let id: number | string = ''
            await act(async () => {
                id = lemonToast.error('boom')
                await jest.advanceTimersByTimeAsync(300)
            })
            expect(toast.isActive(id)).toBe(true)

            // Age the toast past the grace window, then navigate.
            await act(async () => {
                await jest.advanceTimersByTimeAsync(1500)
                lemonToast.dismissStaleErrors()
            })
            expect(toast.isActive(id)).toBe(false)
        })

        it('keeps a just-raised error and any success toast', async () => {
            render(<ToastContainer autoClose={false} />)
            let successId: number | string = ''
            let errorId: number | string = ''
            await act(async () => {
                successId = lemonToast.success('saved')
                await jest.advanceTimersByTimeAsync(300)
            })
            await act(async () => {
                errorId = lemonToast.error('boom')
                await jest.advanceTimersByTimeAsync(300)
            })

            await act(async () => {
                lemonToast.dismissStaleErrors()
            })
            // The error is younger than the grace window; the success is never a dismiss target.
            expect(toast.isActive(errorId)).toBe(true)
            expect(toast.isActive(successId)).toBe(true)
        })

        it('spares an error pinned open with autoClose:false, even when aged past the grace window', async () => {
            render(<ToastContainer autoClose={false} />)
            let id: number | string = ''
            await act(async () => {
                // An actionable prompt whose only exit is its own button (e.g. a re-auth block).
                id = lemonToast.error('re-authenticate to continue', { autoClose: false })
                await jest.advanceTimersByTimeAsync(300)
            })
            expect(toast.isActive(id)).toBe(true)

            await act(async () => {
                await jest.advanceTimersByTimeAsync(1500)
                lemonToast.dismissStaleErrors()
            })
            expect(toast.isActive(id)).toBe(true)
        })
    })
})
