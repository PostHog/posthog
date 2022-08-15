import { appEditorUrl, authorizedUrlsLogic, validateProposedURL } from 'scenes/toolbar-launch/authorizedUrlsLogic'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { urls } from 'scenes/urls'

describe('the authorized urls logic', () => {
    let logic: ReturnType<typeof authorizedUrlsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/trend/': (req) => {
                    if (JSON.parse(req.url.searchParams.get('events') || '[]')?.[0]?.throw) {
                        return [500, { status: 0, detail: 'error from the API' }]
                    }
                    return [200, { result: ['result from api'] }]
                },
            },
        })
        initKeaTests()
        logic = authorizedUrlsLogic()
        logic.mount()
    })

    it('encodes an app url correctly', () => {
        expect(appEditorUrl('http://127.0.0.1:8000')).toEqual(
            '/api/user/redirect_to_site/?userIntent=add-action&appUrl=http%3A%2F%2F127.0.0.1%3A8000'
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
                proposedUrlValidationErrors: { url: 'Please type a valid URL or domain.' },
            })
        })
    })

    describe('validating proposed URLs', () => {
        const testCases = [
            { proposedUrl: 'https://valid.*.example.com', validityMessage: undefined },
            {
                proposedUrl: 'https://notsovalid.*.*',
                validityMessage:
                    'You can only wildcard subdomains. If you wildcard the domain or TLD, people might be able to gain access to your PostHog data.',
            },
            {
                proposedUrl: 'https://*.*.*',
                validityMessage:
                    'You can only wildcard subdomains. If you wildcard the domain or TLD, people might be able to gain access to your PostHog data.',
            },
            { proposedUrl: 'https://valid*.example.com', validityMessage: undefined },
            { proposedUrl: 'https://*.valid.com', validityMessage: undefined },
            {
                proposedUrl: 'https://not.*.valid.*',
                validityMessage:
                    'You can only wildcard subdomains. If you wildcard the domain or TLD, people might be able to gain access to your PostHog data.',
            },
        ]

        testCases.forEach((testCase) => {
            it(`a proposal of "${testCase.proposedUrl}" has validity message "${testCase.validityMessage}"`, () => {
                expect(validateProposedURL(testCase.proposedUrl, [])).toEqual(testCase.validityMessage)
            })
        })

        it('fails if the proposed URL is already authorized', () => {
            expect(validateProposedURL('https://valid.*.example.com', ['https://valid.*.example.com'])).toBe(
                'This URL is already registered.'
            )
            expect(
                validateProposedURL('https://valid.and-not-already-authorized.example.com', [
                    'https://valid.*.example.com',
                ])
            ).toBe(undefined)
        })
    })
})
