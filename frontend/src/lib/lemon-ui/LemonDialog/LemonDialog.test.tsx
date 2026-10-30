import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor, waitForElementToBeRemoved } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useValues } from 'kea'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { initKeaTests } from '~/test/init'

import { LemonDialog, LemonFormDialog } from './LemonDialog'
import { lemonDialogLogic } from './lemonDialogLogic'

function DialogName(): JSX.Element {
    const { form } = useValues(lemonDialogLogic)
    return <span>{form.name}</span>
}

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

    function renderDialog(
        onSubmit: (values: Record<string, any>) => void | Promise<void>,
        shouldAwaitSubmit = true
    ): void {
        render(
            <LemonFormDialog
                dialogKey="test-dialog"
                title="Test dialog"
                shouldAwaitSubmit={shouldAwaitSubmit}
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

    it.each([
        ['Cancel', true, 0],
        ['Submit', true, 1],
        ['Cancel', false, 0],
        ['Submit', false, 1],
    ])(
        'pressing Enter on the focused %s button only clicks it (await submit: %s)',
        async (button, awaitSubmit, submits) => {
            const onSubmit = jest.fn().mockResolvedValue(undefined)

            renderDialog(onSubmit, awaitSubmit)
            screen.getByText(button).closest('button')?.focus()
            await userEvent.keyboard('{Enter}')

            await waitForElementToBeRemoved(() => screen.queryByText('Submit'))
            expect(onSubmit).toHaveBeenCalledTimes(submits)
        }
    )

    it.each(['Cancel', 'Submit'])('calls the imperative form close callback after %s', async (button) => {
        const onAfterClose = jest.fn()
        act(() => {
            LemonDialog.openForm({
                title: 'Test dialog',
                initialValues: { name: 'a name' },
                content: <DialogName />,
                onSubmit: jest.fn(),
                onAfterClose,
            })
        })

        expect(await screen.findByText('a name')).toBeInTheDocument()
        await userEvent.click(screen.getByText(button))

        await waitFor(() => expect(onAfterClose).toHaveBeenCalledTimes(1))
        expect(screen.queryByText('Test dialog')).not.toBeInTheDocument()
    })
})
