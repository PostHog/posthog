import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AIConsentPopoverWrapper } from './AIConsentPopoverWrapper'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

async function confirmConsent(): Promise<void> {
    await userEvent.click(await screen.findByText('I allow AI analysis in this organization'))
    await userEvent.click(await screen.findByText('Enable AI analysis'))
}

function renderWrapper(): void {
    render(
        <Provider>
            <AIConsentPopoverWrapper ignoreDismissal>
                <button>Ask Max</button>
            </AIConsentPopoverWrapper>
        </Provider>
    )
}

describe('AIConsentPopoverWrapper', () => {
    beforeEach(() => {
        localStorage.clear()
        jest.clearAllMocks()
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        organizationLogic.mount()
    })

    // The org PATCH is what flips `dataProcessingAccepted`, and the approved action re-fires as soon
    // as it resolves. If the prompt were still driven purely by that value, a slow round-trip would
    // leave it on screen and the user would be asked to accept the same legal terms twice.
    it('hides the consent prompt on confirm without waiting for the organization update', async () => {
        let resolvePatch: (() => void) | undefined
        useMocks({
            patch: {
                '/api/organizations/:id': async () => {
                    await new Promise<void>((resolve) => {
                        resolvePatch = resolve
                    })
                    return [200, { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: true }]
                },
            },
        })

        renderWrapper()
        await confirmConsent()

        await waitFor(() => {
            expect(screen.queryByText('I allow AI analysis in this organization')).not.toBeInTheDocument()
        })

        resolvePatch?.()
    })

    it('brings the prompt back and surfaces an error when the organization update fails', async () => {
        useMocks({
            patch: {
                '/api/organizations/:id': () => [500, { detail: 'nope' }],
            },
        })

        renderWrapper()
        await confirmConsent()

        await waitFor(() => {
            expect(lemonToast.error).toHaveBeenCalled()
        })
        expect(await screen.findByText('I allow AI analysis in this organization')).toBeInTheDocument()
    })
})
