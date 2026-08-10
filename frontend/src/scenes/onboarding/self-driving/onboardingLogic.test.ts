import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { onboardingLogic } from './onboardingLogic'

describe('onboardingLogic', () => {
    let logic: ReturnType<typeof onboardingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = onboardingLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('persists both onboarding completion signals', async () => {
        await expectLogic(logic, () => {
            logic.actions.completeOnboarding()
        }).toDispatchActions([
            (action) => {
                if (action.type !== logic.actionTypes.updateCurrentTeam) {
                    return false
                }
                expect(action.payload).toMatchObject({
                    completed_snippet_onboarding: true,
                    has_completed_onboarding_for: { [ProductKey.PRODUCT_ANALYTICS]: true },
                })
                return true
            },
        ])
    })

    it('short-circuits when a completion is already in flight', async () => {
        logic.actions.setIsCompleting(true)
        await expectLogic(logic, () => {
            logic.actions.completeOnboarding()
        }).toNotHaveDispatchedActions(['updateCurrentTeam'])
    })

    it('enables selected tool recipes before completing onboarding', async () => {
        const bodies: unknown[] = []
        useMocks({
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/product_enablement/`]: async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, { results: { session_replay: 'enabled' } }]
                },
            },
        })

        await logic.asyncActions.completeOnboarding('improve_experience')

        expect(bodies).toEqual([{ products: ['session_replay'] }])
    })
})
