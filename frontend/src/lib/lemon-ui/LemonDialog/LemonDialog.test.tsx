import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, waitForElementToBeRemoved } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { initKeaTests } from '~/test/init'

import { LemonFormDialog } from './LemonDialog'

describe('LemonFormDialog', () => {
    let captureException: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        // react-modal needs an app element to hide from screen readers on open.
        document.body.innerHTML = '<div id="root"></div>'
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
        await userEvent.click(screen.getByRole('button', { name: 'Submit' }))
    }

    const submitViaEnter = async (): Promise<void> => {
        screen.getByRole('textbox').focus()
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
        expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument()
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
        expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument()
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

        await waitForElementToBeRemoved(() => screen.queryByRole('button', { name: 'Submit' }))
        expect(onSubmit).toHaveBeenCalled()
        expect(captureException).not.toHaveBeenCalled()
    })
})
