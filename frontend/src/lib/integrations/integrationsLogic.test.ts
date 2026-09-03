import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import apiReal, { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationKind, IntegrationType } from '~/types'

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
                '/api/environments/:team_id/integrations/': () => [200, { results: integrationsPayload }],
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
