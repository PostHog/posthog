import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { initKeaTests } from '~/test/init'

import { conversionGoalOptionsLogic } from './conversionGoalOptionsLogic'

describe('conversionGoalOptionsLogic', () => {
    let logic: ReturnType<typeof conversionGoalOptionsLogic.build>
    let actionCount: number
    let customEventCount: number
    let hiddenCustomEventCount: number

    beforeEach(() => {
        actionCount = 0
        customEventCount = 0
        hiddenCustomEventCount = 0
        useMocks({
            get: {
                '/api/projects/:team/actions/': () => [
                    200,
                    { count: actionCount, results: Array.from({ length: actionCount }, (_, id) => ({ id })) },
                ],
                '/api/projects/:team/event_definitions': ({ request }) => {
                    const excludesHidden = new URL(request.url).searchParams.get('exclude_hidden') === 'true'
                    const count = excludesHidden ? customEventCount - hiddenCustomEventCount : customEventCount
                    return [200, { count, results: [] }]
                },
            },
        })
    })

    const mountLogic = (): void => {
        initKeaTests()
        logic = conversionGoalOptionsLogic.build()
        logic.mount()
    }

    const waitForCounts = async (): Promise<void> => {
        await expectLogic(actionsModel).toDispatchActions(['loadActionsSuccess'])
        await expectLogic(logic).toDispatchActions(['loadCustomEventCountSuccess'])
    }

    it('holds off until both counts have loaded', async () => {
        mountLogic()

        // Answering early makes the picker flash a zero state on every load.
        expect(logic.values.hasNoConversionGoalOptions).toBe(false)

        await waitForCounts()
        expect(logic.values.hasNoConversionGoalOptions).toBe(true)
    })

    // Either kind of goal is enough on its own, so gating on actions alone would hide the picker from
    // projects that only send custom events.
    test.each([
        ['an action', 1, 0],
        ['a custom event', 0, 1],
        ['both', 2, 3],
    ])('keeps the picker when the project has %s', async (_label, actions, customEvents) => {
        actionCount = actions as number
        customEventCount = customEvents as number
        mountLogic()
        await waitForCounts()
        expect(logic.values.hasNoConversionGoalOptions).toBe(false)
    })

    it('shows the zero state when every custom event is hidden', async () => {
        // The picker lists custom events with exclude_hidden, so a count without it leaves the user
        // on the empty list this zero state exists to replace.
        customEventCount = 3
        hiddenCustomEventCount = 3
        mountLogic()
        await waitForCounts()
        expect(logic.values.hasNoConversionGoalOptions).toBe(true)
    })
})
