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

import { fireEvent, getByLabelText, getByRole, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

import { initKeaTests } from '../../test/init'
import { createExportServiceHandlers } from './api-mocks'
import { useMocks } from '../../mocks/jest'
import userEvent from '@testing-library/user-event'
import { Export } from './ViewExport'
import { router } from 'kea-router/lib/router'
import ReactModal from 'react-modal'

ReactModal.setAppElement('*')

// Required as LemonSelect uses this when we click on the select button.
global.ResizeObserver = require('resize-observer-polyfill')

jest.setTimeout(5000)

describe('Export', () => {
    it('can trigger historical export', async () => {
        const exportId = '123'
        const name = `test-export-${Math.random().toString(36).substring(7)}`
        const { handlers } = createExportServiceHandlers({
            [exportId]: {
                id: exportId.toString(),
                name: name,
                team_id: 1,
                status: 'RUNNING',
                paused: false,
                created_at: new Date().toISOString(),
                last_updated_at: new Date().toISOString(),
                interval: 'hour' as const,
                destination: {
                    type: 'S3',
                    config: {
                        bucket_name: 'my-bucket',
                        region: 'us-east-1',
                        prefix: 'posthog-events',
                        aws_access_key_id: 'accessKeyId',
                        aws_secret_access_key: 'secretAccessKey',
                    },
                },
            },
        })
        useMocks(handlers)
        initKeaTests()

        // Set the location to the export page, such that the component can get
        // the exportId from the url.
        router.actions.push(`/export/${exportId}`)

        render(<Export />)

        // // Wait for a button to appear with the text "Historical export"
        const historicalExportButton = await screen.findByRole(
            'button',
            { name: /Historical export/i },
            {
                // TODO: use fake timers so we don't need to wait for API latency
                timeout: 5000,
            }
        )

        // Click the button
        userEvent.click(historicalExportButton)

        // Wait for the form to appear
        const form = await screen.findByRole(
            'form',
            {
                // NOTE: for some reason the form is hidden, possibly because we
                // are attaching to the top level element, which will be marked
                // as aria-hidden on modal becoming visible(?)
                hidden: true,
            },
            { timeout: 5000 }
        )

        // Fill out the form
        const startDate = getByLabelText(form, /Start Date/i)
        fireEvent.change(startDate, { target: { value: '2021-01-01T01:02:03' } })

        const endDate = getByLabelText(form, /End Date/i)
        fireEvent.change(endDate, { target: { value: '2021-01-02T01:02:03' } })

        // Submit the form
        const submitButton = getByRole(form, 'button', {
            name: /trigger export/i,
            // NOTE: for some reason the form is hidden, possibly because we
            // are attaching to the top level element, which will be marked
            // as aria-hidden on modal becoming visible(?)
            hidden: true,
        })
        userEvent.click(submitButton)

        // Get the runs table, and wait for the specified dates to appear in the
        // list. Note that we do not rely on any implementation details of the
        // API here, but rely on the fact that the component should refresh the
        // runs table when the export is created.
        const runsTable = await screen.findByRole('table', {}, { timeout: 5000 })
        await waitFor(() => {
            expect(runsTable).toHaveTextContent(/2021-01-01 01:02:03/)
            expect(runsTable).toHaveTextContent(/2021-01-02 01:02:03/)
        })
    }, 20000)
})

beforeAll(() => {
    // The LemonTable rendering results in the console.error log:
    //
    // Warning: validateDOMNesting(...): <div> cannot appear as a child of <tr>.
    //
    // this is due to including the Loader elements as a div directly inside the
    // table row. Rather than patching this, which is a bit of a pain and out of
    // scope of the addition of these tests, I have disabled the warning for the
    // duration of this file.
    const originalError = console.error
    jest.spyOn(console, 'error').mockImplementation(
        (message: string, ...args: any[]) =>
            !message.includes('Warning: validateDOMNesting') && originalError(message, ...args)
    )
})
