import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { agenticAuthorizeLogic } from './agenticAuthorizeLogic'

jest.mock('posthog-js')

describe('agenticAuthorizeLogic', () => {
    let logic: ReturnType<typeof agenticAuthorizeLogic.build>
    let errorToast: jest.SpyInstance
    let confirmResponse: [number, any?]

    const startConfirm = (): void => {
        logic = agenticAuthorizeLogic()
        logic.mount()
        logic.actions.setState('valid_state')
        logic.actions.setAgenticAuthorizationValues({ scoped_organizations: ['org-1'], scoped_teams: [1] })
        logic.actions.submitAgenticAuthorization()
    }

    beforeEach(() => {
        errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('id')
        useMocks({
            get: {
                '/api/projects': () => [200, { results: [] }],
            },
            post: {
                '/api/agentic/authorize/confirm/': () => confirmResponse,
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        errorToast.mockRestore()
        logic?.unmount()
    })

    it.each<[string, [number, any?]]>([
        ['a 200 with an empty object body', [200, {}]],
        ['a 204 with no body', [204]],
    ])('surfaces an error and stops submitting when confirm returns %s', async (_label, response) => {
        confirmResponse = response
        startConfirm()

        await expectLogic(logic).toDispatchActions(['submitAgenticAuthorizationFailure']).toMatchValues({
            isAgenticAuthorizationSubmitting: false,
        })

        expect(errorToast).toHaveBeenCalledWith('Something went wrong while authorizing. Try again.', expect.anything())
        expect(posthog.capture).toHaveBeenCalledWith('agentic authorize confirm failed', {
            reason: 'missing_redirect_url',
            retryable: true,
        })
    })

    it.each([
        [
            'expired_or_invalid_state',
            400,
            'This authorization request expired. Start it again from the app that sent you here.',
        ],
        ['team_not_accessible', 403, 'You do not have access to that project. Pick a project you can access.'],
        [
            'partner_deactivated',
            403,
            'the requesting app is no longer active, so PostHog cannot finish the authorization.',
        ],
    ])('maps the %s error to a specific message', async (code, status, message) => {
        confirmResponse = [status as number, { error: code }]
        startConfirm()

        await expectLogic(logic).toDispatchActions(['submitAgenticAuthorizationFailure']).toMatchValues({
            isAgenticAuthorizationSubmitting: false,
        })

        expect(errorToast).toHaveBeenCalledWith(message, expect.anything())
        expect(posthog.capture).toHaveBeenCalledWith('agentic authorize confirm failed', {
            reason: code,
            retryable: expect.any(Boolean),
        })
    })

    it('confirms a paying partner without asking for a project', async () => {
        const redirectUrl = 'https://app.example.com/callback?code=example_code&state=valid_state'
        let confirmBody: unknown
        useMocks({
            get: {
                '/api/agentic/authorize/pending/': () => [
                    200,
                    {
                        partner_name: 'Example App',
                        scopes: [],
                        pays_for_customers: true,
                        partner_organization_name: null,
                    },
                ],
            },
            post: {
                '/api/agentic/authorize/confirm/': async ({ request }) => {
                    confirmBody = await request.json()
                    return [200, { redirect_url: redirectUrl }]
                },
            },
        })
        logic = agenticAuthorizeLogic()
        logic.mount()
        logic.actions.setState('valid_state')
        await expectLogic(logic, () => logic.actions.loadPendingAuth()).toDispatchActions(['loadPendingAuthSuccess'])

        const originalLocation = window.location
        Object.defineProperty(window, 'location', {
            configurable: true,
            writable: true,
            value: { ...originalLocation, href: originalLocation.href },
        })
        try {
            await expectLogic(logic, () => logic.actions.submitAgenticAuthorization()).toDispatchActions([
                'submitAgenticAuthorizationSuccess',
            ])

            expect(confirmBody).toEqual({ state: 'valid_state' })
            expect(window.location.href).toBe(redirectUrl)
        } finally {
            Object.defineProperty(window, 'location', { configurable: true, writable: true, value: originalLocation })
        }
    })
})
