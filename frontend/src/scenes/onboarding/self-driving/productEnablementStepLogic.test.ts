import { MOCK_TEAM_ID } from 'lib/api.mock'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { productEnablementStepLogic } from './productEnablementStepLogic'

describe('productEnablementStepLogic', () => {
    let logic: ReturnType<typeof productEnablementStepLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = productEnablementStepLogic()
        logic.mount()
    })

    it('enables one product per request, so an admin-gated failure cannot take down the batch', async () => {
        const bodies: any[] = []
        useMocks({
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/product_enablement/`]: async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, { results: { session_replay: 'enabled' } }]
                },
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': () => [200, { product_intents: [] }],
            },
        })

        const onSuccess = jest.fn()
        await logic.asyncActions.enableProduct('session_replay', onSuccess)
        expect(bodies).toEqual([{ products: ['session_replay'] }])
        expect(onSuccess).toHaveBeenCalled()
        expect(logic.values.enablingProduct).toBeNull()
    })

    it('does not advance the step on failure', async () => {
        useMocks({
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/product_enablement/`]: () => [
                    403,
                    { detail: 'Only project admins can enable products that change these settings' },
                ],
            },
        })

        const onSuccess = jest.fn()
        await logic.asyncActions.enableProduct('session_replay', onSuccess)
        expect(onSuccess).not.toHaveBeenCalled()
        expect(logic.values.enablingProduct).toBeNull()
    })

    it('auto-enables only the goal products that are still off', async () => {
        const bodies: any[] = []
        useMocks({
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/product_enablement/`]: async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, { results: { error_tracking: 'enabled' } }]
                },
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': () => [200, { product_intents: [] }],
            },
        })
        // Mock team: replay already on, error tracking off - fix_issues wants both.
        await teamLogic.asyncActions.loadCurrentTeam()

        await logic.asyncActions.configureToolsForGoal('fix_issues')
        expect(bodies).toEqual([{ products: ['error_tracking'] }])
    })
})
