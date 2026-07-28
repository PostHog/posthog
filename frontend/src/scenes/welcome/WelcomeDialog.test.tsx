/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { WelcomeDialog } from './WelcomeDialog'
import { welcomeDialogLogic } from './welcomeDialogLogic'

const INVITED_USER: UserType = { ...MOCK_DEFAULT_USER, is_organization_first_user: false }

const WELCOME_URL = '/api/organizations/@current/welcome/current/'

async function renderDialogWithFailure(status: number, body: Record<string, unknown>): Promise<void> {
    useMocks({ get: { [WELCOME_URL]: () => [status, body] } })
    initKeaTests()
    userLogic.mount()
    userLogic.actions.loadUserSuccess(INVITED_USER)
    const logic = welcomeDialogLogic()
    logic.mount()
    render(
        <Provider>
            <WelcomeDialog />
        </Provider>
    )
    await waitFor(() => expect(logic.values.welcomeDataLoading).toBe(false))
}

describe('WelcomeDialog', () => {
    beforeEach(() => {
        window.localStorage.clear()
        window.sessionStorage.clear()
        silenceKeaLoadersErrors()
    })
    afterEach(resumeKeaLoadersErrors)

    it('stays out of the way while the session is blocked by a 2FA gate', async () => {
        await renderDialogWithFailure(403, {
            detail: '2FA verification required',
            code: 'two_factor_verification_required',
        })

        expect(screen.queryByText(/We couldn't load your team's activity/)).not.toBeInTheDocument()
        expect(document.querySelector('[data-attr="welcome-dialog"]')).not.toBeInTheDocument()
    })

    it('offers a retry when the welcome data itself failed to load', async () => {
        await renderDialogWithFailure(500, { detail: 'Server error' })

        expect(screen.getByText(/We couldn't load your team's activity/)).toBeInTheDocument()
    })
})
