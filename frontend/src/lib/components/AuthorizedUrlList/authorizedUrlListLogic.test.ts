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
            query: null,
        })
        logic.mount()
    })

    it('encodes an app url correctly', () => {
        expect(appEditorUrl('http://127.0.0.1:8000')).toEqual(
            '/api/user/redirect_to_site/?userIntent=add-action&apiURL=http%3A%2F%2Flocalhost&appUrl=http%3A%2F%2F127.0.0.1%3A8000'
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
    })
})
