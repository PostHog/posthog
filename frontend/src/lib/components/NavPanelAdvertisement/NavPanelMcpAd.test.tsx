import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { agentConnectionLogic } from 'lib/components/MCPHint/agentConnectionLogic'

import type { ConnectedAppApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { NavPanelMcpAd } from './NavPanelMcpAd'
import { MCP_AD_LOGIC_PROPS } from './NavPanelMcpCard'

const AGENT_APP: ConnectedAppApi = {
    id: 'agent',
    name: 'Claude Code',
    logo_uri: null,
    scopes: ['openid'],
    authorized_at: '2026-06-18T00:00:00Z',
    is_verified: false,
    is_first_party: false,
    requires_access_confirmation: false,
    is_self_registered: true,
}

describe('NavPanelMcpAd', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['no agent connected', [200, []], false, 1, true],
        ['an agent connected', [200, [AGENT_APP]], false, 1, false],
        ['a failed lookup', [500, { detail: 'boom' }], false, 1, false],
        ['a dismissed card', [200, []], true, 0, false],
    ] as const)('with %s', async (_, response, dismissed, expectedRequests, shown) => {
        let requests = 0
        useMocks({
            get: {
                '/api/oauth/connected-apps/': () => {
                    requests += 1
                    return response
                },
            },
        })
        initKeaTests()
        if (dismissed) {
            const dismissLogic = navPanelAdvertisementLogic(MCP_AD_LOGIC_PROPS)
            dismissLogic.mount()
            dismissLogic.actions.hideAdvertisement()
        }

        render(
            <Provider>
                <NavPanelMcpAd />
            </Provider>
        )

        await waitFor(() => expect(requests).toBe(expectedRequests))
        await waitFor(() =>
            expect(agentConnectionLogic.findMounted()?.values.connectedAppsLoading ?? false).toBe(false)
        )
        expect(screen.queryByText('Connect your AI agent') !== null).toBe(shown)
    })
})
