import { expectLogic } from 'kea-test-utils'

import type { ConnectedApp } from 'scenes/settings/user/connectedAppsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { agentConnectionLogic, hasAgentConnection } from './agentConnectionLogic'

const AGENT_APP: ConnectedApp = {
    id: 'agent',
    name: 'Claude Code',
    logo_uri: null,
    scopes: ['openid'],
    authorized_at: '2026-06-18T00:00:00Z',
    is_verified: false,
    is_first_party: false,
    is_setup_wizard: false,
}
const WIZARD_APP: ConnectedApp = {
    ...AGENT_APP,
    id: 'wizard',
    name: 'PostHog Wizard',
    is_first_party: true,
    is_setup_wizard: true,
}

describe('agentConnectionLogic', () => {
    let logic: ReturnType<typeof agentConnectionLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['no connection', [], false],
        ['only the setup wizard', [WIZARD_APP], false],
        ['the setup wizard and an agent', [WIZARD_APP, AGENT_APP], true],
    ])('hasAgentConnection with %s', (_name, apps, expected) => {
        expect(hasAgentConnection(apps)).toBe(expected)
    })

    it('leaves the connection unknown when the lookup fails', async () => {
        useMocks({ get: { '/api/oauth/connected-apps/': () => [500, { detail: 'boom' }] } })
        initKeaTests()
        logic = agentConnectionLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.hasConnectedAgent).toBeNull()
    })

    it('keeps a newer connected response when an older empty one arrives late', async () => {
        const releases: Array<() => void> = []
        const responses = [[], [AGENT_APP]]
        let call = 0
        useMocks({
            get: {
                '/api/oauth/connected-apps/': async () => {
                    const body = responses[Math.min(call++, responses.length - 1)]
                    await new Promise<void>((resolve) => releases.push(resolve))
                    return [200, body]
                },
            },
        })
        initKeaTests()
        logic = agentConnectionLogic()
        logic.mount()
        logic.actions.loadConnectedApps()
        await expectLogic(logic).toMatchValues({ connectedAppsLoading: true })
        while (releases.length < 2) {
            await new Promise((r) => setTimeout(r, 0))
        }

        releases[1]()
        await expectLogic(logic).toDispatchActions(['loadConnectedAppsSuccess'])
        releases[0]()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.hasConnectedAgent).toBe(true)
    })
})
