import { MOCK_TEAM_ID, api } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    AuthorizedUrlListType,
    SuggestedDomain,
    appEditorUrl,
    authorizedUrlListLogic,
    directToolbarUrl,
    filterNotAuthorizedUrls,
    validateProposedUrl,
} from './authorizedUrlListLogic'

describe('the authorized urls list logic', () => {
    let logic: ReturnType<typeof authorizedUrlListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend/': (req) => {
                    if (JSON.parse(req.url.searchParams.get('events') || '[]')?.[0]?.throw) {
                        return [500, { status: 0, detail: 'error from the API' }]
                    }
                    return [200, { result: ['result from api'] }]
                },
            },
            patch: {
                '/api/projects/:team': [200, {}],
            },
        })
        initKeaTests()
        logic = authorizedUrlListLogic({
            type: AuthorizedUrlListType.TOOLBAR_URLS,
            actionId: null,
            experimentId: null,
            productTourId: null,
            query: null,
        })
        logic.mount()
    })

    it('encodes an app url correctly', () => {
        expect(appEditorUrl('http://127.0.0.1:8000')).toEqual(
            '/api/user/redirect_to_site/?userIntent=add-action&uiHost=http%3A%2F%2Flocalhost&appUrl=http%3A%2F%2F127.0.0.1%3A8000'
        )
    })

    it('can be launched with adding a new URL focussed', async () => {
        router.actions.push(`${urls.toolbarLaunch()}?addNew=true`)
        await expectLogic(logic).toDispatchActions(['newUrl'])
    })

    it('can be launchd without focussing adding new URL', async () => {
        router.actions.push(urls.toolbarLaunch())
        await expectLogic(logic).toNotHaveDispatchedActions(['newUrl'])
    })

    describe('the proposed URL form', () => {
        it('shows errors when the value is invalid', async () => {
            await expectLogic(logic, () => {
                logic.actions.setProposedUrlValue('url', 'not a domain or url')
            }).toMatchValues({
                proposedUrl: { url: 'not a domain or url' },
                proposedUrlChanged: true,
                proposedUrlHasErrors: true,
                proposedUrlValidationErrors: { url: 'Please enter a valid URL' },
            })
        })
    })

    describe('validating proposed URLs', () => {
        const testCases = [
            { proposedUrl: 'https://valid.*.example.com', validityMessage: undefined },
            {
                proposedUrl: 'https://notsovalid.*.*',
                validityMessage: 'Wildcards can only be used for subdomains',
            },
            {
                proposedUrl: 'https://*.*.*',
                validityMessage: 'Wildcards can only be used for subdomains',
            },
            { proposedUrl: 'https://valid*.example.com', validityMessage: undefined },
            { proposedUrl: 'https://*.valid.com', validityMessage: undefined },
            {
                proposedUrl: 'https://not.*.valid.*',
                validityMessage: 'Wildcards can only be used for subdomains',
            },
            {
                proposedUrl: 'http://localhost:*',
                validityMessage: 'Wildcards are not allowed in the port position',
            },
            {
                proposedUrl: 'http://valid.example.com:*',
                validityMessage: 'Wildcards are not allowed in the port position',
            },
            {
                proposedUrl: 'http://*.localhost:3000',
                validityMessage: undefined,
            },
            {
                proposedUrl: 'http://*.valid.com:3000',
                validityMessage: undefined,
            },
        ]

        testCases.forEach((testCase) => {
            it(`a proposal of "${testCase.proposedUrl}" has validity message "${testCase.validityMessage}"`, () => {
                expect(validateProposedUrl(testCase.proposedUrl, [], false)).toEqual(testCase.validityMessage)
            })
        })

        it('can refuse wildcards', () => {
            expect(validateProposedUrl('https://*.example.com', [], false, false)).toEqual('Wildcards are not allowed')
            expect(validateProposedUrl('https://*.example.com', [], false, true)).toEqual(undefined)
            expect(validateProposedUrl('https://*.example.com', [], false)).toEqual(undefined)
        })

        it('fails if the proposed URL is already authorized', () => {
            expect(validateProposedUrl('https://valid.*.example.com', ['https://valid.*.example.com'], false)).toBe(
                'This URL already is registered'
            )
            expect(
                validateProposedUrl(
                    'https://valid.and-not-already-authorized.example.com',
                    ['https://valid.*.example.com'],
                    false
                )
            ).toBe(undefined)
        })
    })
    describe('recording domain type', () => {
        beforeEach(() => {
            logic = authorizedUrlListLogic({
                type: AuthorizedUrlListType.RECORDING_DOMAINS,
                actionId: null,
                experimentId: null,
                productTourId: null,
                query: null,
            })
            logic.mount()
        })
        it('gets initial domains from recording_domains on the current team', () => {
            expectLogic(logic).toMatchValues({
                authorizedUrls: ['https://recordings.posthog.com/'],
            })
        })
        it('addUrl the recording_domains on the team', () => {
            jest.spyOn(api, 'update')

            expectLogic(logic, () => logic.actions.addUrl('http://*.example.com')).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}`, {
                recording_domains: ['https://recordings.posthog.com/', 'http://*.example.com'],
            })
        })

        describe('validating proposed recording domains', () => {
            const testCases = [
                { proposedUrl: 'https://valid.*.example.com', validityMessage: undefined },
                {
                    proposedUrl: 'https://not.valid.com/path',
                    validityMessage: "Please enter a valid domain (URLs with a path aren't allowed)",
                },
                {
                    proposedUrl: 'https://not.*.valid.*',
                    validityMessage: 'Wildcards can only be used for subdomains',
                },
                {
                    proposedUrl: 'capacitor://localhost',
                    validityMessage: undefined,
                },
            ]

            testCases.forEach((testCase) => {
                it(`a proposal of "${testCase.proposedUrl}" has validity message "${testCase.validityMessage}"`, () => {
                    expect(validateProposedUrl(testCase.proposedUrl, [], true)).toEqual(testCase.validityMessage)
                })
            })
        })
    })

    describe('directToolbarUrl', () => {
        const parseHash = (url: string): Record<string, unknown> => {
            const hash = url.split('#__posthog=')[1]
            return JSON.parse(decodeURIComponent(hash))
        }

        it('always includes uiHost from window.location.origin', () => {
            // JSDOM sets window.location.origin to 'http://localhost'
            const params = parseHash(directToolbarUrl('https://example.com'))
            expect(params.uiHost).toBe('http://localhost')
        })

        it('does not include apiURL', () => {
            const params = parseHash(directToolbarUrl('https://example.com'))
            expect(params.apiURL).toBeUndefined()
        })

        it('sets required action fields', () => {
            const params = parseHash(directToolbarUrl('https://example.com', { token: 'phc_abc' }))
            expect(params.action).toBe('ph_authorize')
            expect(params.toolbarVersion).toBe('toolbar')
            expect(params.instrument).toBe(true)
            expect(params.token).toBe('phc_abc')
        })

        it('includes user identity fields', () => {
            const params = parseHash(
                directToolbarUrl('https://example.com', {
                    userEmail: 'user@example.com',
                    distinctId: 'distinct_123',
                })
            )
            expect(params.userEmail).toBe('user@example.com')
            expect(params.distinctId).toBe('distinct_123')
        })

        it('sets userIntent to add-action when no specific intent', () => {
            const params = parseHash(directToolbarUrl('https://example.com'))
            expect(params.userIntent).toBe('add-action')
        })

        it('sets userIntent to edit-action when actionId is provided', () => {
            const params = parseHash(directToolbarUrl('https://example.com', { actionId: 42 }))
            expect(params.userIntent).toBe('edit-action')
            expect(params.actionId).toBe(42)
        })

        it('sets userIntent to edit-experiment when experimentId is provided', () => {
            const params = parseHash(directToolbarUrl('https://example.com', { experimentId: 99 }))
            expect(params.userIntent).toBe('edit-experiment')
            expect(params.experimentId).toBe(99)
        })

        it('sets userIntent to edit-product-tour when productTourId is provided', () => {
            const params = parseHash(directToolbarUrl('https://example.com', { productTourId: 'tour_1' }))
            expect(params.userIntent).toBe('edit-product-tour')
            expect(params.productTourId).toBe('tour_1')
        })

        it('sets userIntent to add-product-tour when productTourId is "new"', () => {
            const params = parseHash(directToolbarUrl('https://example.com', { productTourId: 'new' }))
            expect(params.userIntent).toBe('add-product-tour')
            expect(params.productTourId).toBeUndefined()
        })

        it('includes dataAttributes when provided', () => {
            const params = parseHash(
                directToolbarUrl('https://example.com', { dataAttributes: ['data-id', 'data-attr'] })
            )
            expect(params.dataAttributes).toEqual(['data-id', 'data-attr'])
        })

        it('puts params in the hash fragment of appUrl', () => {
            const url = directToolbarUrl('https://mysite.com/page?q=1')
            expect(url.startsWith('https://mysite.com/page?q=1#__posthog=')).toBe(true)
        })

        it('uiHost is window.location.origin regardless of apiURL option', () => {
            // Simulates reverse proxy customer: their api_host is their proxy,
            // but uiHost should always be window.location.origin (the PostHog app)
            const params = parseHash(directToolbarUrl('https://customer.com'))
            expect(params.uiHost).toBe('http://localhost')
            expect(params.apiURL).toBeUndefined()
        })

        it('does not include toolbarFlagsKey when not provided', () => {
            const params = parseHash(directToolbarUrl('https://example.com'))
            expect(params.toolbarFlagsKey).toBeUndefined()
        })

        it('includes toolbarFlagsKey when provided', () => {
            const params = parseHash(directToolbarUrl('https://example.com', { toolbarFlagsKey: 'flags_key_xyz' }))
            expect(params.toolbarFlagsKey).toBe('flags_key_xyz')
        })
    })

    describe('filterNotAuthorizedUrls', () => {
        const testUrls: SuggestedDomain[] = [
            { url: 'https://1.wildcard.com', count: 1 },
            { url: 'https://2.wildcard.com', count: 1 },
            { url: 'https://a.single.io', count: 1 },
            { url: 'https://a.sub.b.multi-wildcard.com', count: 1 },
            { url: 'https://a.not.b.multi-wildcard.com', count: 1 },
            { url: 'https://not.valid.io', count: 1 },
        ]

        it('suggests all if empty', () => {
            expect(filterNotAuthorizedUrls(testUrls, [])).toEqual(testUrls)
        })

        it('allows specific domains', () => {
            expect(filterNotAuthorizedUrls(testUrls, ['https://a.single.io'])).toEqual([
                { url: 'https://1.wildcard.com', count: 1 },
                { url: 'https://2.wildcard.com', count: 1 },
                { url: 'https://a.sub.b.multi-wildcard.com', count: 1 },
                { url: 'https://a.not.b.multi-wildcard.com', count: 1 },
                { url: 'https://not.valid.io', count: 1 },
            ])
        })

        it('filters wildcard domains', () => {
            expect(
                filterNotAuthorizedUrls(testUrls, ['https://*.wildcard.com', 'https://*.sub.*.multi-wildcard.com'])
            ).toEqual([
                { url: 'https://a.single.io', count: 1 },
                { url: 'https://a.not.b.multi-wildcard.com', count: 1 },
                { url: 'https://not.valid.io', count: 1 },
            ])
        })

        it('filters out invalid URLs like paths without domains', () => {
            const urlsWithInvalidPaths: SuggestedDomain[] = [
                { url: '/', count: 10 },
                { url: '/billing', count: 5 },
                { url: '/settings/project', count: 3 },
                { url: 'https://valid.example.com', count: 2 },
                { url: 'not-a-url', count: 1 },
            ]
            expect(filterNotAuthorizedUrls(urlsWithInvalidPaths, [])).toEqual([
                { url: 'https://valid.example.com', count: 2 },
            ])
        })
    })
})
