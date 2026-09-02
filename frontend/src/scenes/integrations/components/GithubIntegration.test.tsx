import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { GithubIntegration } from './GithubIntegration'

describe('GithubIntegration', () => {
    let captureSpy: jest.SpyInstance
    let installRequests: Record<string, unknown>[]

    beforeEach(() => {
        installRequests = []
        useMocks({
            get: {
                '/api/environments/:team_id/integrations': { results: [] },
                '/api/projects/:team_id/integrations/github/available_installations/': { installations: [] },
                '/api/users/@me/integrations/github/install_requests/': () => [
                    200,
                    { results: installRequests, install_url: 'https://github.com/apps/posthog-dev/installations/new' },
                ],
            },
        })
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        captureSpy.mockRestore()
        cleanup()
    })

    const clickConnect = async (element: JSX.Element): Promise<void> => {
        render(<Provider>{element}</Provider>)
        const button = await screen.findByText('Connect account')
        await userEvent.click(button)
    }

    const connectClicks = (): Record<string, unknown>[] =>
        captureSpy.mock.calls.filter((call) => call[0] === 'integration_connect_clicked').map((call) => call[1])

    it('reports the surface it was rendered on', async () => {
        await clickConnect(<GithubIntegration connectSurface="settings" />)

        await waitFor(() =>
            expect(connectClicks()).toEqual([
                { integration: 'github', integration_kind: 'github', surface: 'settings' },
            ])
        )
    })

    // The OAuth landing page reports every kind's connect click for itself, so giving `connectSurface`
    // a default would make one click on that page count twice and inflate the connect metric.
    it('stays silent without a surface, so the landing page is the only reporter there', async () => {
        await clickConnect(<GithubIntegration />)

        expect(connectClicks()).toEqual([])
    })

    it.each([
        ['pending', 'GitHub sent your request', 'Copy message for your org owner'],
        ['approved', 'An organization owner approved the PostHog app for', 'Finish connecting'],
    ])('shows the %s install request with its action', async (status, text, action) => {
        installRequests = [
            {
                id: '018f0000-0000-7000-8000-000000000001',
                github_login: 'octocat',
                status,
                installation_id: status === 'approved' ? '55555' : null,
                account_login: status === 'approved' ? 'posthog-org' : null,
                account_type: null,
                requested_at: '2026-08-18T00:00:00Z',
                resolved_at: null,
            },
        ]

        render(
            <Provider>
                <GithubIntegration connectSurface="settings" />
            </Provider>
        )

        expect(await screen.findByText(text, { exact: false })).toBeInTheDocument()
        expect(screen.getByText(action)).toBeInTheDocument()
    })
})
