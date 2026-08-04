import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { wizardCloudRunLogic } from './wizardCloudRunLogic'

jest.mock('posthog-js', () => ({
    capture: jest.fn(),
}))

const githubIntegration: IntegrationType = {
    id: 1,
    kind: 'github',
    display_name: 'my-org',
    icon_url: '',
    config: {},
    created_at: '2026-01-01T00:00:00Z',
}

describe('wizardCloudRunLogic — GitHub connect instrumentation', () => {
    let logic: ReturnType<typeof wizardCloudRunLogic.build>
    let integrations: ReturnType<typeof integrationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        integrations = integrationsLogic()
        integrations.mount()
        logic = wizardCloudRunLogic()
        logic.mount()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    it('reports a click and, once the integration appears, reports the connect as completed', async () => {
        logic.actions.githubConnectClicked()

        expect(posthog.capture).toHaveBeenCalledWith(
            'wizard sync github connect clicked',
            expect.objectContaining({ mode: 'cloud' })
        )
        expect(logic.values.githubConnectAttempted).toBe(true)

        // The OAuth handoff is a full-page redirect: the integration only shows up once the return
        // leg's GET reloads the team's integrations.
        await expectLogic(logic, () => {
            integrations.actions.loadIntegrationsSuccess([githubIntegration])
        }).toDispatchActions([logic.actionCreators.githubConnectAttemptHandled()])

        expect(posthog.capture).toHaveBeenCalledWith(
            'wizard sync github connected',
            expect.objectContaining({ mode: 'cloud' })
        )
        // The flag doesn't outlive the connect it was set for — a later disconnect/reconnect must
        // report its own completion rather than silently reusing a stale attempt.
        expect(logic.values.githubConnectAttempted).toBe(false)
    })

    it('does not report a connect for a user who already had GitHub connected on arrival', async () => {
        integrations.actions.loadIntegrationsSuccess([githubIntegration])

        expect(posthog.capture).not.toHaveBeenCalledWith('wizard sync github connected', expect.anything())
        expect(logic.values.githubConnectAttempted).toBe(false)
    })
})
