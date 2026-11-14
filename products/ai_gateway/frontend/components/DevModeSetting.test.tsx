import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import {
    aiGatewayDevTokensCreate,
    aiGatewayDevTokensRevokeCreate,
    aiGatewayDevTokensUsageRetrieve,
} from '../generated/api'
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
    token_cap_usd: '1000.00',
    token_cap_min_usd: '5.00',
    default_cap_usd: '25.00',
    ttl_seconds: 28800,
    ttl_min_seconds: 3600,
    ttl_max_seconds: 604800,
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

    it.each([
        ['the default cap fits', '20.00', null, true],
        ['the picked cap is exactly what is left', '40.00', 10, true],
        ['the picked cap is more than what is left', '40.00', 10.01, false],
        ['the picked cap is below the minimum', '0.00', 4.99, false],
        ['the picked cap has cents', '0.00', 19.99, true],
        ['the picked cap has fractions of a cent', '0.00', 19.995, false],
        ['the picked cap is above the maximum', '0.00', 1000.01, false],
    ])('allows minting when %s', (_name, usedUsd, pickedCap, canMint) => {
        devModeLogic.actions.loadUsageSuccess({ ...USAGE, daily_cap_usd: '50.00', used_usd: usedUsd })
        if (pickedCap !== null) {
            devModeLogic.actions.setCapUsd(pickedCap)
        }

        expect(devModeLogic.values.canMint).toBe(canMint)
    })

    it('mints with the picked cap and lifetime, and a usage reload keeps the pick', async () => {
        jest.mocked(aiGatewayDevTokensCreate).mockResolvedValue(MINTED)
        devModeLogic.actions.loadUsageSuccess(USAGE)
        expect([devModeLogic.values.capUsd, devModeLogic.values.ttlSeconds]).toEqual([25, 28800])

        devModeLogic.actions.setCapUsd(1000)
        devModeLogic.actions.setTtlSeconds(604800)
        devModeLogic.actions.loadUsageSuccess(USAGE)
        devModeLogic.actions.mint()

        await waitFor(() =>
            expect(aiGatewayDevTokensCreate).toHaveBeenCalledWith({ cap_usd: '1000.00', ttl_seconds: 604800 })
        )
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
