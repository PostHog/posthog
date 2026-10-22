import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { aiGatewayDevTokensRevokeCreate, aiGatewayDevTokensUsageRetrieve } from '../generated/api'
import type { DevTokenUsageApi, MintedDevTokenApi } from '../generated/api.schemas'
import { devModeLogic } from '../logics/devModeLogic'
import { DevModeSetting } from './DevModeSetting'

jest.mock('../generated/api', () => ({
    aiGatewayDevTokensUsageRetrieve: jest.fn(),
    aiGatewayDevTokensCreate: jest.fn(),
    aiGatewayDevTokensRevokeCreate: jest.fn(),
    aiGatewayDevTokensCliAuthorizeCreate: jest.fn(),
}))

const USAGE: DevTokenUsageApi = {
    daily_cap_usd: '50.00',
    used_usd: '25.00',
    token_cap_usd: '25.00',
    ttl_seconds: 28800,
    tokens: [],
}

const MINTED: MintedDevTokenApi = {
    id: '00000000-0000-0000-0000-000000000001',
    token: 'phe_fixture_bearer_value',
    cap_usd: '25.00',
    expires_at: '2026-10-21T08:00:00Z',
    gateway_url: 'https://gateway.example.test',
    product: 'dev',
}

describe('<DevModeSetting />', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(aiGatewayDevTokensUsageRetrieve).mockResolvedValue(USAGE)
        devModeLogic.mount()
    })

    afterEach(() => {
        cleanup()
        devModeLogic.unmount()
    })

    it('hides the minted token from session replay and autocapture', () => {
        devModeLogic.actions.mintSuccess(MINTED)
        render(
            <Provider>
                <DevModeSetting />
            </Provider>
        )

        const token = screen.getByText(MINTED.token)
        expect(token.closest('.ph-no-capture')).not.toBeNull()
    })

    it.each([
        ['succeeds', true],
        ['fails', false],
    ])('holds the revoke pending state until the request %s', async (_name, succeeds) => {
        let settle: () => void = () => {}
        jest.mocked(aiGatewayDevTokensRevokeCreate).mockReturnValue(
            new Promise((resolve, reject) => {
                settle = () => (succeeds ? resolve({ revoked_count: 2 }) : reject({ detail: 'nope' }))
            })
        )

        devModeLogic.actions.revokeToken(null)
        expect(devModeLogic.values.revoking).toEqual({ id: null })

        settle()
        await waitFor(() => expect(devModeLogic.values.revoking).toBeNull())
    })
})
