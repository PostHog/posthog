import { MOCK_TEAM_ID } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import apiReal, { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationKind, IntegrationType } from '~/types'

import * as integrationsApi from 'products/integrations/frontend/generated/api'
import type {
    GitHubAvailableInstallationsResponseApi,
    IntegrationConfigApi,
} from 'products/integrations/frontend/generated/api.schemas'

import { integrationsLogic } from './integrationsLogic'

const githubIntegration = (overrides: Partial<IntegrationType> = {}): IntegrationType =>
    ({
        id: 42,
        kind: 'github',
        display_name: 'PostHog',
        icon_url: '',
        config: { installation_id: '12345', account: { name: 'PostHog', type: 'Organization' } },
        created_at: '2026-08-18T00:00:00Z',
        errors: '',
        installation_shared: false,
        installation_status: 'connected',
        ...overrides,
    }) as IntegrationType

describe('integrationsLogic', () => {
    let logic: ReturnType<typeof integrationsLogic.build>
    let createSpy: jest.SpyInstance
    let integrationsPayload: IntegrationType[]
    let repoRequests: { integrationId: string; offset: string }[]

    beforeEach(async () => {
        integrationsPayload = []
        repoRequests = []
        // Handlers reset after every test, so register them per test.
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/github/available_installations/': {
                    installations: [],
                    personal_github_connected: false,
                    personal_discovery_status: 'not_connected',
                },
                '/api/projects/:team_id/integrations/': () => [200, { results: integrationsPayload }],
                '/api/projects/:team_id/integrations/:id/github_repos/': ({ params, request }) => {
                    const offset = new URL(request.url).searchParams.get('offset') ?? '0'
                    repoRequests.push({ integrationId: String(params.id), offset })
                    const repositories = Array.from({ length: 100 }, (_, i) => ({
                        id: Number(offset) + i,
                        name: `repo${Number(offset) + i}`,
                        full_name: `posthog/repo${Number(offset) + i}`,
                    }))
                    return [200, { repositories, has_more: offset === '0', total: 200 }]
                },
            },
        })
        initKeaTests()
        logic = integrationsLogic()
        logic.mount()
        // Drain the mount-time load so each test controls the next list response.
        await expectLogic(logic).toDispatchActions(['loadIntegrationsSuccess'])
        createSpy = jest.spyOn(apiReal.integrations, 'create')
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    describe('GitHub discovery freshness', () => {
        const discovery = (id: string): GitHubAvailableInstallationsResponseApi => ({
            discovery_id: id,
            discovered_at: new Date().toISOString(),
            personal_github_connected: true,
            personal_github_login: 'synthetic-reader',
            personal_discovery_status: 'ok',
            installations: [
                {
                    installation_id: id,
                    account_name: 'synthetic-owner',
                    account_type: 'Organization',
                    source_team_id: null,
                    source_team_name: null,
                },
            ],
        })

        it.each(['invalidate', 'newer response', 'project switch'])(
            'rejects a delayed response after %s',
            async (change) => {
                let resolve!: (response: GitHubAvailableInstallationsResponseApi) => void
                const pending = new Promise<GitHubAvailableInstallationsResponseApi>((done) => {
                    resolve = done
                })
                const request = jest
                    .spyOn(integrationsApi, 'integrationsGithubAvailableInstallationsRetrieve')
                    .mockReturnValueOnce(pending)
                logic.actions.loadGithubAvailableInstallations()
                if (change === 'invalidate') {
                    logic.actions.invalidateGithubSuggestions()
                } else if (change === 'newer response') {
                    request.mockResolvedValueOnce(discovery('new'))
                    logic.actions.loadGithubAvailableInstallations()
                    await waitFor(() =>
                        expect(logic.values.githubAvailableInstallations?.[0].installation_id).toBe('new')
                    )
                } else {
                    teamLogic.actions.loadCurrentTeamSuccess({
                        ...teamLogic.values.currentTeam!,
                        id: 999,
                        project_id: 999,
                    })
                }
                resolve(discovery('old'))
                await pending
                await new Promise<void>((done) => queueMicrotask(done))
                expect(logic.values.githubAvailableInstallations?.[0]?.installation_id ?? null).toBe(
                    change === 'newer response' ? 'new' : null
                )
            }
        )

        it('hides invalidated suggestions and exposes refresh failure for retry', async () => {
            const request = jest
                .spyOn(integrationsApi, 'integrationsGithubAvailableInstallationsRetrieve')
                .mockResolvedValueOnce(discovery('old'))
            logic.actions.loadGithubAvailableInstallations()
            await waitFor(() => expect(logic.values.githubAvailableInstallations).toHaveLength(1))
            request.mockRejectedValueOnce(new Error('synthetic failure'))
            logic.actions.loadGithubAvailableInstallations()
            expect(logic.values.githubAvailableInstallations).toBeNull()
            await waitFor(() => expect(logic.values.githubDiscoveryFailed).toBe(true))
            expect(logic.values.githubAvailableInstallationsResponseLoading).toBe(false)
        })

        it('refreshes suggestions when polling sees changed GitHub connections', async () => {
            const request = jest
                .spyOn(integrationsApi, 'integrationsGithubAvailableInstallationsRetrieve')
                .mockResolvedValue(discovery('fresh'))
            logic.actions.subscribeGithubSuggestions()
            integrationsPayload = [githubIntegration()]
            await expectLogic(logic, () => logic.actions.loadIntegrations()).toDispatchActions([
                'loadIntegrationsSuccess',
                'loadGithubAvailableInstallations',
            ])
            expect(request).toHaveBeenCalled()
            logic.actions.unsubscribeGithubSuggestions()
        })

        it('discovers once when switching projects with a mounted GitHub surface', async () => {
            const request = jest
                .spyOn(integrationsApi, 'integrationsGithubAvailableInstallationsRetrieve')
                .mockResolvedValue(discovery('fresh'))
            logic.actions.subscribeGithubSuggestions()
            await expectLogic(logic).toFinishAllListeners()
            request.mockClear()
            integrationsPayload = [githubIntegration()]

            await expectLogic(logic, () =>
                teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, id: 999, project_id: 999 })
            ).toFinishAllListeners()

            expect(request).toHaveBeenCalledTimes(1)
            expect(request).toHaveBeenCalledWith('999')
            logic.actions.unsubscribeGithubSuggestions()
        })

        it('keeps loaded integrations when the same project refreshes', async () => {
            integrationsPayload = [githubIntegration()]
            await expectLogic(logic, () => logic.actions.loadIntegrations()).toFinishAllListeners()

            teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam! })

            expect(logic.values.integrations).toHaveLength(1)
        })

        it.each([false, true])(
            'discards a delayed link completion after switching projects, failure=%s',
            async (fails) => {
                let finish!: () => void
                const pending = new Promise<IntegrationConfigApi>((resolve, reject) => {
                    finish = () =>
                        fails ? reject(new Error('synthetic failure')) : resolve({ id: 42 } as IntegrationConfigApi)
                })
                jest.spyOn(integrationsApi, 'integrationsGithubLinkExistingCreate').mockReturnValue(pending)
                const toast = jest.spyOn(lemonToast, 'success')
                const reload = jest.spyOn(logic.actions, 'loadIntegrations')
                logic.actions.linkExistingGithubInstallation('12345')
                teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, id: 999, project_id: 999 })
                await expectLogic(logic).toDispatchActions(['loadIntegrationsSuccess'])
                reload.mockClear()

                finish()
                await expectLogic(logic).toFinishAllListeners()

                expect(toast).not.toHaveBeenCalled()
                expect(reload).not.toHaveBeenCalled()
                expect(logic.values.linkedGithubInstallation).toBeNull()
                expect(logic.values.linkedGithubInstallationLoading).toBe(false)
            }
        )
    })

    describe('GitHub repositories', () => {
        it.each([
            ['all', 1],
            ['selected', 2],
        ])('with repository_selection=%s it fetches %i page(s)', async (repositorySelection, expectedPages) => {
            integrationsPayload = [
                githubIntegration({
                    config: { installation_id: '12345', repository_selection: repositorySelection },
                }),
            ]
            await expectLogic(logic, () => logic.actions.loadIntegrations()).toDispatchActions([
                'loadIntegrationsSuccess',
            ])

            await expectLogic(logic, () => logic.actions.loadGitHubRepositories(42)).toFinishAllListeners()

            expect(repoRequests.filter((r) => r.integrationId === '42')).toHaveLength(expectedPages)
            expect(logic.values.getGitHubRepositoriesTotal(42)).toBe(200)
            expect(logic.values.githubRepositoriesLoading).toBe(false)
        })

        it('clears the cached total when a reload starts so a scope change cannot show a stale count', async () => {
            integrationsPayload = [
                githubIntegration({ config: { installation_id: '12345', repository_selection: 'selected' } }),
            ]
            await expectLogic(logic, () => logic.actions.loadIntegrations()).toDispatchActions([
                'loadIntegrationsSuccess',
            ])
            await expectLogic(logic, () => logic.actions.loadGitHubRepositories(42)).toFinishAllListeners()
            expect(logic.values.getGitHubRepositoriesTotal(42)).toBe(200)

            // A reload (e.g. after repository_selection flips via polling) drops the stale total
            // immediately, before the refetch resolves.
            logic.actions.loadGitHubRepositories(42)
            expect(logic.values.getGitHubRepositoriesTotal(42)).toBeNull()

            await expectLogic(logic).toFinishAllListeners()
        })
    })

    describe('deleteIntegration', () => {
        let dialogProps: any

        beforeEach(() => {
            dialogProps = null
            jest.spyOn(LemonDialog, 'open').mockImplementation((props: any) => {
                dialogProps = props
            })
        })

        it.each([
            [
                'last team reference',
                false,
                'This uninstalls the PostHog app from PostHog on GitHub and disconnects it from every PostHog project and personal account that uses it.',
            ],
            [
                'shared with another project',
                true,
                'This project stops using GitHub. The PostHog app stays installed on GitHub because other projects or accounts still use it.',
            ],
        ])('explains what disconnecting GitHub does when %s', async (_name, installationShared, description) => {
            integrationsPayload = [githubIntegration({ installation_shared: installationShared })]
            await expectLogic(logic, () => logic.actions.loadIntegrations()).toDispatchActions([
                'loadIntegrationsSuccess',
            ])

            logic.actions.deleteIntegration(42)

            expect(dialogProps.title).toBe('Disconnect GitHub?')
            expect(dialogProps.description).toBe(description)
        })

        it.each([false, true])('refreshes suggestions after disconnect with failure=%s', async (fails) => {
            integrationsPayload = [githubIntegration()]
            await expectLogic(logic, () => logic.actions.loadIntegrations()).toDispatchActions([
                'loadIntegrationsSuccess',
            ])
            const discoveryRequest = jest
                .spyOn(integrationsApi, 'integrationsGithubAvailableInstallationsRetrieve')
                .mockResolvedValue({
                    installations: [],
                    personal_github_connected: false,
                    personal_discovery_status: 'not_connected',
                    personal_github_login: null,
                    discovery_id: 'fresh',
                    discovered_at: new Date().toISOString(),
                })
            let finish!: () => void
            const deletion = new Promise<IntegrationType>((resolve, reject) => {
                finish = () => (fails ? reject(new ApiError('synthetic failure', 500)) : resolve(githubIntegration()))
            })
            jest.spyOn(apiReal.integrations, 'delete').mockReturnValue(deletion)
            jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
            logic.actions.deleteIntegration(42)
            const click = dialogProps.primaryButton.onClick()
            expect(logic.values.githubAvailableInstallations).toBeNull()
            expect(logic.values.githubAvailableInstallationsResponseLoading).toBe(true)
            logic.actions.loadGithubAvailableInstallations()
            expect(discoveryRequest).not.toHaveBeenCalled()
            finish()
            await click
            await waitFor(() => expect(discoveryRequest).toHaveBeenCalledTimes(1))
            await waitFor(() => expect(logic.values.githubAvailableInstallationsResponseLoading).toBe(false))
        })

        it('treats a 404 on delete as already disconnected and reloads', async () => {
            integrationsPayload = [githubIntegration()]
            await expectLogic(logic, () => logic.actions.loadIntegrations()).toDispatchActions([
                'loadIntegrationsSuccess',
            ])
            jest.spyOn(apiReal.integrations, 'delete').mockRejectedValue(new ApiError('Not found', 404))
            const infoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => 'toast')
            const errorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')

            logic.actions.deleteIntegration(42)
            await expectLogic(logic, async () => {
                await dialogProps.primaryButton.onClick()
            }).toDispatchActions(['loadIntegrations'])

            expect(infoSpy).toHaveBeenCalledWith('Already disconnected.')
            expect(errorSpy).not.toHaveBeenCalled()
        })
    })

    describe('polling', () => {
        it('polls integrations only while at least one surface is subscribed', async () => {
            jest.useFakeTimers()
            const discoveryRequest = jest.spyOn(integrationsApi, 'integrationsGithubAvailableInstallationsRetrieve')

            logic.actions.startPolling()
            logic.actions.startPolling()
            expect(logic.cache.disposables.registry.has('poll')).toBe(true)

            await expectLogic(logic, () => {
                jest.advanceTimersByTime(30_000)
            }).toDispatchActions(['loadIntegrations'])

            logic.actions.stopPolling()
            expect(logic.cache.disposables.registry.has('poll')).toBe(true)
            logic.actions.stopPolling()
            expect(logic.cache.disposables.registry.has('poll')).toBe(false)
            expect(discoveryRequest).not.toHaveBeenCalled()
        })
    })

    describe('handleOauthCallback', () => {
        it('redirects stripe marketplace callbacks to the confirmation page without POSTing', async () => {
            await expectLogic(logic, () => {
                logic.actions.handleOauthCallback('stripe' as IntegrationKind, {
                    code: 'ac_123',
                    stripe_user_id: 'acct_456',
                    account_id: 'acc_789',
                    user_id: 'usr_1',
                })
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toContain('/integrations/stripe/confirm-install')
            expect(router.values.searchParams).toEqual({
                code: 'ac_123',
                stripe_user_id: 'acct_456',
                account_id: 'acc_789',
                user_id: 'usr_1',
            })
        })

        it('omits empty account_id and user_id when redirecting to the confirmation page', async () => {
            await expectLogic(logic, () => {
                logic.actions.handleOauthCallback('stripe' as IntegrationKind, {
                    code: 'ac_123',
                    stripe_user_id: 'acct_456',
                })
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toContain('/integrations/stripe/confirm-install')
            expect(router.values.searchParams).toEqual({
                code: 'ac_123',
                stripe_user_id: 'acct_456',
            })
        })

        // Slack answers `access_denied` when a workspace parks the install as an admin-approval
        // request, and the user's next move is the connect button on the landing page. A toast is
        // gone by then, so that page takes the reason in the URL and keeps it on screen; the
        // settings page has no such banner and still needs the toast.
        it.each([
            [
                'the integration landing page',
                '%2Fintegrations%2Fslack',
                `/project/${MOCK_TEAM_ID}/integrations/slack`,
                true,
            ],
            [
                'the settings page',
                '%2Fproject%2F228502%2Fsettings%2Fproject-integrations',
                '/project/228502/settings/project-integrations',
                false,
            ],
        ])('carries a rejected connect back to %s', async (_name, encodedNext, expectedPathname, expectBanner) => {
            const errorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')

            await expectLogic(logic, () => {
                logic.actions.handleOauthCallback('slack' as IntegrationKind, {
                    state: `next=${encodedNext}&token=csrf-tok`,
                    error: 'access_denied',
                })
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toBe(expectedPathname)
            expect(router.values.searchParams.integration_error).toBe(expectBanner ? 'access_denied' : undefined)
            if (expectBanner) {
                expect(errorSpy).not.toHaveBeenCalled()
            } else {
                expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining('admin to approve new apps'))
            }
        })

        it('does not create the integration when the OAuth state token no longer matches the cookie', async () => {
            // A stale/expired flow: the cookie minted at authorize time is gone or changed, so the token
            // carried in the state can't match. The callback must recover by redirecting back rather than
            // POST a create, so an expired (or forged) state can never link an integration.
            document.cookie = 'ph_oauth_state=a-different-token'
            const state = 'next=%2Fproject%2F228502%2Fsettings%2Fproject-integrations&token=csrf-tok'

            await expectLogic(logic, () => {
                logic.actions.handleOauthCallback('slack' as IntegrationKind, { state, code: 'oauth-code' })
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toBe('/project/228502/settings/project-integrations')

            document.cookie = 'ph_oauth_state=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
        })

        // The data warehouse source wizard shows the reason beside its connect button, so both a
        // provider rejection and an expired state reach it in the URL rather than as a toast that
        // is gone before the user retries.
        it.each([
            ['a rejected connect', { error: 'access_denied' }, 'access_denied'],
            ['an expired state', { code: 'oauth-code' }, 'posthog_state_expired'],
        ])('carries %s back to the source wizard', async (_name, extraParams, expectedError) => {
            const errorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
            document.cookie = 'ph_oauth_state=a-different-token'

            await expectLogic(logic, () => {
                logic.actions.handleOauthCallback('meta-ads' as IntegrationKind, {
                    state: 'next=%2Fdata-warehouse%2Fnew-source%3Fkind%3Dmeta-ads&token=csrf-tok',
                    ...extraParams,
                })
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toBe(`/project/${MOCK_TEAM_ID}/data-warehouse/new-source`)
            expect(router.values.searchParams.integration_error).toBe(expectedError)
            expect(router.values.searchParams.kind).toBe('meta-ads')
            expect(errorSpy).not.toHaveBeenCalled()

            document.cookie = 'ph_oauth_state=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
        })

        describe('integration create team scoping', () => {
            let requestedTeamIds: string[]

            beforeEach(() => {
                requestedTeamIds = []
                document.cookie = 'ph_oauth_state=csrf-tok'
                useMocks({
                    post: {
                        '/api/environments/:team_id/integrations/': ({ params }) => {
                            requestedTeamIds.push(String(params.team_id))
                            return [201, { id: 7, kind: 'slack' }]
                        },
                    },
                })
            })

            afterEach(() => {
                document.cookie = 'ph_oauth_state=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
            })

            it('creates the integration against the team carried in the OAuth state', async () => {
                // The callback is a full-page round-trip on a non-project-scoped URL, so the SPA's
                // current team is the user's default team here (MOCK_TEAM_ID) — not team 228502,
                // which the state says initiated the flow.
                const state = 'next=%2Fproject%2F228502%2Fsettings%2Fproject-integrations&token=csrf-tok&team_id=228502'

                await expectLogic(logic, () => {
                    logic.actions.handleOauthCallback('slack' as IntegrationKind, { state, code: 'oauth-code' })
                }).toFinishAllListeners()

                expect(createSpy).toHaveBeenCalledWith({ kind: 'slack', config: { state, code: 'oauth-code' } }, 228502)
                expect(requestedTeamIds).toEqual(['228502'])
                expect(router.values.location.pathname).toBe('/project/228502/settings/project-integrations')
                expect(router.values.searchParams.integration_id).toBe(7)
            })

            it('falls back to the current team when the OAuth state carries no team_id', async () => {
                // In-flight flows started before team_id was added to the state keep the old behavior.
                const state = 'next=%2Fproject%2F228502%2Fsettings%2Fproject-integrations&token=csrf-tok'

                await expectLogic(logic, () => {
                    logic.actions.handleOauthCallback('slack' as IntegrationKind, { state, code: 'oauth-code' })
                }).toFinishAllListeners()

                expect(createSpy).toHaveBeenCalledWith(
                    { kind: 'slack', config: { state, code: 'oauth-code' } },
                    undefined
                )
                expect(requestedTeamIds).toEqual([String(MOCK_TEAM_ID)])
            })
        })
    })
})
