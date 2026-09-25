import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, waitForElementToBeRemoved } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { initKeaTests } from '~/test/init'

import { LemonDialog, LemonFormDialog } from './LemonDialog'

describe('LemonFormDialog', () => {
    let captureException: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    function renderDialog(onSubmit: (values: Record<string, any>) => void | Promise<void>): void {
        render(
            <LemonFormDialog
                dialogKey="test-dialog"
                title="Test dialog"
                shouldAwaitSubmit
                initialValues={{ name: 'a name' }}
                content={
                    <LemonField name="name">
                        <LemonInput />
                    </LemonField>
                }
                onSubmit={onSubmit}
            />
        )
    }

    const submitViaButton = async (): Promise<void> => {
        await userEvent.click(screen.getByText('Submit'))
    }

    const submitViaEnter = async (): Promise<void> => {
        // click focuses the input through userEvent, so the focus state update is act-wrapped
        await userEvent.click(screen.getByRole('textbox'))
        await userEvent.keyboard('{Enter}')
    }

    it.each([
        ['button click', submitViaButton],
        ['enter key', submitViaEnter],
    ])('keeps the dialog open when the submit rejects (%s)', async (_mode, submit) => {
        const onSubmit = jest.fn().mockRejectedValue(new Error('rejected'))

        renderDialog(onSubmit)
        await submit()

        await waitFor(() => expect(onSubmit).toHaveBeenCalled())
        // Dialog stays open so the user can correct and retry.
        expect(screen.getByText('Submit')).toBeInTheDocument()
    })

    it.each([
        ['unexpected Error', new Error('boom'), true],
        ['5xx ApiError', new ApiError('server error', 500), true],
        ['4xx validation ApiError', new ApiError('reserved name', 400), false],
    ])('only captures unexpected failures, not user-validation errors (%s)', async (_desc, error, shouldCapture) => {
        const onSubmit = jest.fn().mockRejectedValue(error)

        renderDialog(onSubmit)
        await submitViaButton()

        await waitFor(() => expect(onSubmit).toHaveBeenCalled())
        expect(screen.getByText('Submit')).toBeInTheDocument()
        if (shouldCapture) {
            expect(captureException).toHaveBeenCalledWith(error)
        } else {
            expect(captureException).not.toHaveBeenCalled()
        }
    })

    it('closes the dialog and does not capture when the submit resolves', async () => {
        const onSubmit = jest.fn().mockResolvedValue(undefined)

        renderDialog(onSubmit)
        await submitViaButton()

        await waitForElementToBeRemoved(() => screen.queryByText('Submit'))
        expect(onSubmit).toHaveBeenCalled()
        expect(captureException).not.toHaveBeenCalled()
    })

    // `openForm` owns the dialog's React root and has to tear it down when the dialog closes, which
    // is easy to do by replacing the caller's `onAfterClose` instead of running it first. A caller
    // that awaits the dialog's outcome (`onAfterClose: () => resolve(null)`) then never hears about
    // a dismissal, and whatever it is holding open stays open forever.
    it.each([
        ['confirmed', 'Submit'],
        ['dismissed', 'Cancel'],
    ])('tells the caller when an imperatively opened dialog is %s', async (_outcome, button) => {
        const onAfterClose = jest.fn()

        LemonDialog.openForm({
            title: 'Imperative dialog',
            initialValues: {},
            onSubmit: () => undefined,
            onAfterClose,
        })
        await userEvent.click(await screen.findByText(button))

        await waitFor(() => expect(onAfterClose).toHaveBeenCalled())
    })
})
