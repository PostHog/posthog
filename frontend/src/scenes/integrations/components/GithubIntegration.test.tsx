import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import type { IntegrationConnectSurface } from 'lib/integrations/utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { GithubIntegration } from './GithubIntegration'

describe('GithubIntegration', () => {
    let captureSpy: jest.SpyInstance
    let installRequests: Record<string, unknown>[]
    let availableInstallations: Record<string, unknown>[]

    beforeEach(() => {
        installRequests = []
        availableInstallations = []
        useMocks({
            get: {
                '/api/projects/:team_id/integrations': { results: [] },
                '/api/projects/:team_id/integrations/github/available_installations/': () => [
                    200,
                    {
                        installations: availableInstallations,
                        personal_github_connected: false,
                        personal_discovery_status: 'ok',
                        personal_github_login: 'synthetic-user',
                        discovery_id: '11111111-1111-4111-8111-111111111111',
                        discovered_at: new Date().toISOString(),
                    },
                ],
                '/api/users/@me/integrations/github/install_requests/': () => [
                    200,
                    { results: installRequests, install_url: 'https://github.com/apps/posthog-dev/installations/new' },
                ],
            },
            post: {
                '/api/projects/:team_id/integrations/github/link_existing/': { id: 1 },
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
        ['settings', 'settings_link_existing'],
        ['inbox_welcome', 'inbox_welcome'],
    ])(
        'reports linking an existing installation with the %s surface as %s',
        async (connectSurface, expectedSurface) => {
            availableInstallations = [{ installation_id: '55555', account_name: 'posthog-org', account_type: null }]

            render(
                <Provider>
                    <GithubIntegration connectSurface={connectSurface as IntegrationConnectSurface} />
                </Provider>
            )

            const button = await screen.findByText(/^Connect to /)
            await userEvent.click(button)

            await waitFor(() =>
                expect(connectClicks()).toEqual([
                    { integration: 'github', integration_kind: 'github', surface: expectedSurface },
                ])
            )
        }
    )

    it.each([
        [
            'a sibling project',
            {
                installation_id: '55555',
                account_name: 'acme',
                account_type: null,
                source_team_id: 7,
                source_team_name: 'Website',
            },
            'and connected to',
        ],
        [
            'the personal GitHub connection',
            {
                installation_id: '55555',
                account_name: 'acme',
                account_type: null,
                source_team_id: null,
                source_team_name: null,
            },
            'Found through your GitHub connection as synthetic-user',
        ],
    ])('says an installation offered from %s is from there', async (_source, installation, expectedSource) => {
        availableInstallations = [installation]

        render(
            <Provider>
                <GithubIntegration connectSurface="settings" />
            </Provider>
        )

        expect(await screen.findByText(expectedSource, { exact: false })).toBeInTheDocument()
    })

    // The label used to fall back to the login of whoever connected the install, which reads as a
    // stranger's account. An install with no account name must say so instead of naming a person.
    it('falls back to the installation id when the account name is missing', async () => {
        availableInstallations = [
            {
                installation_id: '55555',
                account_name: null,
                account_type: null,
                source_team_id: 7,
                source_team_name: 'Website',
            },
        ]

        render(
            <Provider>
                <GithubIntegration connectSurface="settings" />
            </Provider>
        )

        expect(await screen.findByText('installation 55555')).toBeInTheDocument()
    })

    it('reports what the link-existing banner offered', async () => {
        availableInstallations = [
            {
                installation_id: '55555',
                account_name: 'acme',
                account_type: null,
                source_team_id: 7,
                source_team_name: 'Website',
            },
            {
                installation_id: '66666',
                account_name: null,
                account_type: null,
                source_team_id: null,
                source_team_name: null,
            },
        ]

        render(
            <Provider>
                <GithubIntegration connectSurface="settings" />
            </Provider>
        )

        await screen.findByText('Choose an account')
        expect(captureSpy.mock.calls.filter((call) => call[0] === 'integration_link_existing_offered')).toHaveLength(0)
        await userEvent.click(screen.getByText('Choose an account'))
        await waitFor(() =>
            expect(
                captureSpy.mock.calls
                    .filter((call) => call[0] === 'integration_link_existing_offered')
                    .map((call) => call[1])
            ).toEqual([
                {
                    discovery_id: '11111111-1111-4111-8111-111111111111',
                    displayed_installation_ids: ['55555', '66666'],
                    response_age_ms: expect.any(Number),
                    integration_kind: 'github',
                    surface: 'settings',
                    installation_count: 2,
                    sibling_installation_count: 1,
                    orphan_installation_count: 1,
                    unnamed_installation_count: 1,
                },
            ])
        )
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
