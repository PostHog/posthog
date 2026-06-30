import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, waitForElementToBeRemoved } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

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
    ])('keeps the dialog open and captures when the submit rejects (%s)', async (_mode, submit) => {
        const error = new Error('rejected')
        const onSubmit = jest.fn().mockRejectedValue(error)

        renderDialog(onSubmit)
        await submit()

        await waitFor(() => expect(captureException).toHaveBeenCalledWith(error))
        // Dialog stays open so the user can correct and retry.
        expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument()
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
