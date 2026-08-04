import '@testing-library/jest-dom'

import { act, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BatchExportScene } from './BatchExportScene'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
    },
}))

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

describe('BatchExportScene', () => {
    beforeEach(() => {
        useMocks({
            get: {
                // Mirrors production: Redshift has no `DestinationTest` implementation, so the request
                // always 404s. Never resolving here simulates that in-flight window deterministically,
                // instead of racing a `findByText` retry against however fast MSW settles the mock.
                '/api/environments/:team_id/batch_exports/test/': () => new Promise(() => {}),
            },
        })
        initKeaTests()
    })

    // Regression: the create page used to gate its entire render behind the destination-test
    // request too. That request always 404s for Redshift, so the page stayed on the loading
    // skeleton indefinitely instead of rendering the form. See BatchExportScene.tsx's loading guard.
    it('renders the create form for a destination with no test endpoint, without waiting on that request', async () => {
        render(
            <Provider>
                <BatchExportScene id={null} service="redshift" />
            </Provider>
        )

        // Flush the microtasks queued by the mounted loaders without waiting on the
        // never-resolving destination-test request.
        await act(async () => {
            await Promise.resolve()
        })

        expect(screen.getByText('Host')).toBeInTheDocument()
    })
})
