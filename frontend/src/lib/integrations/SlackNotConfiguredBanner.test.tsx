import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { integrationsLogic } from './integrationsLogic'
import { SlackNotConfiguredBanner } from './SlackIntegrationHelpers'

describe('SlackNotConfiguredBanner', () => {
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        captureSpy.mockRestore()
        cleanup()
    })

    const impressions = (): Record<string, unknown>[] =>
        captureSpy.mock.calls.filter((call) => call[0] === 'slack_not_configured_banner_shown').map((call) => call[1])

    const renderBanner = (): void => {
        render(
            <Provider>
                <SlackNotConfiguredBanner surface="subscription_wizard" />
            </Provider>
        )
    }

    it('reports one impression with the surface and the integrations the project has', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': {
                    results: [{ id: 1, kind: 'github', display_name: 'org', config: {}, created_at: '2026-01-01' }],
                    next: null,
                },
            },
        })
        const logic = integrationsLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.integrations).not.toBeNull())

        renderBanner()

        expect(impressions()).toEqual([
            {
                surface: 'subscription_wizard',
                integrations_loaded: true,
                integrations_load_failed: false,
                integration_count: 1,
                slack_integration_count: 0,
            },
        ])
    })

    // An unresolved list and a failed load render the same banner as a project with no Slack
    // workspace, so without these two properties the impression count cannot tell them apart.
    it('reports an unresolved integrations list as not loaded', () => {
        useMocks({ get: { '/api/projects/:team_id/integrations/': () => new Promise(() => {}) } })

        renderBanner()

        expect(impressions()).toEqual([
            expect.objectContaining({ integrations_loaded: false, integrations_load_failed: false }),
        ])
    })

    it('reports a failed integrations load', async () => {
        useMocks({ get: { '/api/projects/:team_id/integrations/': () => [500] } })
        const logic = integrationsLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.integrationsLoadFailed).toBe(true))

        renderBanner()

        expect(impressions()).toEqual([
            expect.objectContaining({ integrations_loaded: false, integrations_load_failed: true }),
        ])
    })
})
