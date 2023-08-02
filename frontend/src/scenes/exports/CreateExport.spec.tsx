// Here we test the S3 and Snowflake export creation forms. We use MSW to mock
// out the batch export API calls, and we use the userEvent library to simulate
// user interactions with the form.
//
// We use the screen object from the testing-library/react library to render the
// form and get references to the form elements. We use the waitFor function to
// wait for the form to be rendered before we start interacting with it.
//
// We use the waitFor function again to wait for the form to be submitted before
// we start asserting on the results.
//
// We use the expect function from the jest-dom library to assert on the form
// elements. We use the toBeInTheDocument matcher to assert that the form is
// rendered, and we use the toHaveTextContent matcher to assert that the form
// contains the expected text.
//
// We use ARIA roles, semantics, and labels to make our forms accessible. We use
// these for selection of elements within tests, and we use them to make our
// forms accessible to users with disabilities.

import { getByLabelText, getByRole, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

import { ExportForm } from './ExportForm'
import { initKeaTests } from '../../test/init'
import { createExportServiceHandlers } from './api-mocks'
import { useMocks } from '../../mocks/jest'
import userEvent from '@testing-library/user-event'

// Required as LemonSelect uses this when we click on the select button.
global.ResizeObserver = require('resize-observer-polyfill')

afterEach(() => {
    jest.useRealTimers()
})

jest.setTimeout(5000)

describe('ExportForm', () => {
    it('renders an S3 export form by default and allows submission', async () => {
        const { exports, handlers } = createExportServiceHandlers()
        useMocks(handlers)
        initKeaTests()

        render(<ExportForm exportId={null} />)

        // Wait for the form with aria label "Create Export" to be rendered
        const form = await waitFor(() => {
            const form = screen.getByRole('form')
            expect(form).toBeInTheDocument()
            return form
        })

        // Should be able to input values into the form inputs
        // Generate a random name to avoid conflicts with other tests
        const name = `test-export-${Math.random().toString(36).substring(7)}`
        userEvent.type(getByLabelText(form, 'Name'), name)
        userEvent.type(getByLabelText(form, 'Bucket'), 'test-bucket')
        userEvent.type(getByLabelText(form, 'Key prefix'), 'test-export')
        userEvent.type(getByLabelText(form, 'AWS Access Key ID'), 'test-access-key-id')
        userEvent.type(getByLabelText(form, 'AWS Secret Access Key'), 'test-secret-access-key')

        // Should be able to select values from the form selects. LemonSelect
        // components are not html select elements, so we need to 1. click on
        // the component element to open the dropdown, and 2. click on the
        // dropdown option to select it.
        const frequencyComponent = getByLabelText(form, 'Frequency')
        userEvent.click(frequencyComponent)
        userEvent.click(await screen.findByText('Daily'))

        userEvent.click(getByLabelText(form, 'Region'))
        userEvent.click(await screen.findByText('Canada (Central)'))

        // Should be able to submit the form

        jest.useFakeTimers({ advanceTimers: true })
        userEvent.click(getByRole(form, 'button', { name: 'Save' }))

        // Wait e.g. for the create request to complete
        jest.advanceTimersByTime(5000)

        // Validate that the export was added to the list of exports, with the
        // correct values.
        await waitFor(() => {
            // Filter the exports object values to find an export with the name
            // we specified in the form.
            const [export_] = Object.values(exports).filter((export_: any) => export_.name === name)

            // Validate that the export has the correct values
            expect(export_).toEqual(
                expect.objectContaining({
                    name,
                    interval: 'day',
                    destination: {
                        type: 'S3',
                        config: {
                            bucket_name: 'test-bucket',
                            prefix: 'test-export',
                            region: 'ca-central-1',
                            aws_access_key_id: 'test-access-key-id',
                            aws_secret_access_key: 'test-secret-access-key',
                            batch_window_size: 3600,
                        },
                    },
                })
            )
        })
    })
})
