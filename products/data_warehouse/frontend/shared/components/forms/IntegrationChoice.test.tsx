import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { authorizedIntegrationId, SourceIntegrationChoice, sourceOAuthRedirectUrl } from './IntegrationChoice'

const integration = (id: number, kind: string): IntegrationType => ({ id, kind }) as IntegrationType

describe('SourceIntegrationChoice', () => {
    // Reconnecting mid-setup leaves the field pointing at the replaced connection, which blocks the
    // wizard on the account step with no way forward but starting over.
    it.each([
        ['adopts the connection the callback just created', { integration_id: '7' }, 7],
        ['ignores a connection belonging to another provider', { integration_id: '8' }, null],
        ['ignores an id no connection matches', { integration_id: '99' }, null],
        ['ignores a blank param', { integration_id: '' }, null],
        ['ignores a missing param', {}, null],
    ])('%s', (_name, searchParams, expected) => {
        const integrations = [integration(7, 'linkedin-ads'), integration(8, 'google-ads')]
        expect(authorizedIntegrationId(searchParams, integrations, 'linkedin-ads')).toEqual(expected)
    })

    it('waits for the connection list rather than adopting an unverified id', () => {
        expect(authorizedIntegrationId({ integration_id: '7' }, null, 'linkedin-ads')).toBeNull()
    })
    it.each(['/data-warehouse/new-source', '/onboarding'])(
        'preserves source origin and return destination through OAuth from %s',
        (pathname) => {
            const search = new URLSearchParams({
                kind: 'MetaAds',
                returnUrl: '/project/997/marketing?tab=ad-performance',
                returnLabel: 'Marketing analytics',
                entry_point: 'marketing_analytics_mcp',
            }).toString()
            const redirect = new URL(sourceOAuthRedirectUrl('GoogleAds', pathname, `?${search}`), 'https://example.com')
            expect(Object.fromEntries(redirect.searchParams)).toEqual({
                kind: 'GoogleAds',
                returnUrl: '/project/997/marketing?tab=ad-performance',
                returnLabel: 'Marketing analytics',
                entry_point: 'marketing_analytics_mcp',
            })
            expect(redirect.pathname).toBe(pathname)
        }
    )

    describe('OAuth callback error banner', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/environments/:team_id/integrations': { results: [] },
                    '/api/projects/:team_id/integrations': { results: [] },
                },
            })
            initKeaTests()
        })

        afterEach(() => {
            cleanup()
        })

        // The source name (`BingAds`) and the integration kind (`bing-ads`) differ, and the provider
        // copy is keyed by the integration kind.
        it('describes the error with the integration kind, not the source name', async () => {
            router.actions.push('/data-warehouse/new-source', { kind: 'BingAds', integration_error: 'invalid_client' })
            const sourceConfig = { name: 'BingAds', fields: [] } as unknown as SourceConfigResponseApi
            render(
                <Provider>
                    <SourceIntegrationChoice sourceConfig={sourceConfig} integration="bing-ads" />
                </Provider>
            )
            expect(
                await screen.findByText(/Your Microsoft organization has not enabled the Microsoft Advertising API/)
            ).toBeInTheDocument()
        })
    })

    describe('pending GitHub install request', () => {
        const pendingRequest = {
            id: '018f0000-0000-7000-8000-000000000001',
            github_login: 'synthetic-user',
            status: 'pending',
            installation_id: null,
            account_login: null,
            account_type: null,
            requested_at: '2026-08-18T00:00:00Z',
            resolved_at: null,
        }

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/environments/:team_id/integrations': { results: [] },
                    '/api/projects/:team_id/integrations': { results: [] },
                    '/api/users/@me/integrations/github/install_requests/': () => [
                        200,
                        {
                            results: [pendingRequest],
                            install_url: 'https://github.com/apps/posthog-dev/installations/new',
                        },
                    ],
                },
            })
            initKeaTests()
        })

        afterEach(() => {
            cleanup()
        })

        const renderField = async (kind: string): Promise<void> => {
            const sourceConfig = { name: kind, fields: [] } as unknown as SourceConfigResponseApi
            render(
                <Provider>
                    <SourceIntegrationChoice sourceConfig={sourceConfig} integration={kind} />
                </Provider>
            )
            await screen.findByText(/^Choose .+ connection$/)
        }

        // A user who isn't a GitHub org owner comes back from GitHub to this field with only a
        // request sent, so the message for their owner has to be here, not only in settings.
        it('shows the request on the GitHub connect field', async () => {
            await renderField('github')
            expect(await screen.findByText('Copy message for your org owner')).toBeInTheDocument()
        })

        it('keeps the request off other connect fields', async () => {
            await renderField('hubspot')
            expect(screen.queryByText('Copy message for your org owner')).not.toBeInTheDocument()
        })
    })
})
