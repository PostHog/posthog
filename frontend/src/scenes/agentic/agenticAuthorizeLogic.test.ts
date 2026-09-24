import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { agenticAuthorizeLogic } from './agenticAuthorizeLogic'

jest.mock('posthog-js')

describe('agenticAuthorizeLogic', () => {
    let logic: ReturnType<typeof agenticAuthorizeLogic.build>
    let errorToast: jest.SpyInstance
    let confirmResponse: [number, any?]
    let projectsStatus: number

    const startConfirm = (): void => {
        logic = agenticAuthorizeLogic()
        logic.mount()
        logic.actions.setState('valid_state')
        logic.actions.setAgenticAuthorizationValues({ scoped_organizations: ['org-1'], scoped_teams: [1] })
        logic.actions.submitAgenticAuthorization()
    }

    beforeEach(() => {
        errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('id')
        projectsStatus = 200
        useMocks({
            get: {
                '/api/users/@me/': MOCK_DEFAULT_USER,
                '/api/projects': () => [200, { results: [] }],
                [`/api/organizations/${MOCK_DEFAULT_ORGANIZATION.id}/projects`]: () =>
                    projectsStatus === 200 ? [200, { results: [] }] : [projectsStatus],
            },
            post: {
                '/api/agentic/authorize/confirm/': () => confirmResponse,
            },
        })
        initKeaTests()
        userLogic.mount()
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

    it('loads the projects again when the person picks a different organization', async () => {
        logic = agenticAuthorizeLogic()
        logic.mount()
        logic.actions.loadAllTeams()
        await expectLogic(logic).toDispatchActions(['loadAllTeamsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setAgenticAuthorizationValue('scoped_organizations', [MOCK_DEFAULT_ORGANIZATION.id])
        }).toDispatchActions(['loadAllTeams', 'loadAllTeamsSuccess'])
    })

    it('reports a failed projects load instead of showing an empty picker', async () => {
        projectsStatus = 500
        logic = agenticAuthorizeLogic()
        logic.mount()
        logic.actions.loadAllTeams()

        await expectLogic(logic).toDispatchActions(['loadAllTeamsFailure']).toMatchValues({
            allTeamsFailed: true,
            filteredTeams: undefined,
        })
        expect(posthog.capture).toHaveBeenCalledWith(
            'authorize projects loaded',
            expect.objectContaining({ screen: 'agentic', success: false })
        )
    })
})
