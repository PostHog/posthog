import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { TODAY_RAIL_DEFAULT_HIDDEN } from './todayRailLayout'
import { todayRailLayoutLogic } from './todayRailLayoutLogic'

describe('todayRailLayoutLogic', () => {
    let capture: jest.SpyInstance
    let logic: ReturnType<typeof todayRailLayoutLogic.build>

    const customizedEvents = (): Record<string, any>[] =>
        capture.mock.calls.filter(([name]) => name === 'today rail customized').map(([, properties]) => properties)

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        logic = todayRailLayoutLogic()
        logic.mount()
    })

    it('reports the layout each change leaves behind', () => {
        const [first, second] = logic.values.arrangedPanes
        const hiddenByDefault = TODAY_RAIL_DEFAULT_HIDDEN[0]

        logic.actions.moveRailPane(first, 1)
        logic.actions.toggleRailPane(hiddenByDefault)
        logic.actions.resetRailLayout()

        expect(
            customizedEvents().map(({ action, rail_order, rail_hidden, $set }) => ({
                action,
                lead: rail_order.slice(0, 2),
                rail_hidden,
                customized: $set.today_rail_customized,
                person_hidden: $set.today_rail_hidden,
            }))
        ).toEqual([
            {
                action: 'move',
                lead: [second, first],
                rail_hidden: TODAY_RAIL_DEFAULT_HIDDEN,
                customized: true,
                person_hidden: TODAY_RAIL_DEFAULT_HIDDEN,
            },
            {
                action: 'toggle',
                lead: [second, first],
                rail_hidden: TODAY_RAIL_DEFAULT_HIDDEN.filter((pane) => pane !== hiddenByDefault),
                customized: true,
                person_hidden: TODAY_RAIL_DEFAULT_HIDDEN.filter((pane) => pane !== hiddenByDefault),
            },
            {
                action: 'reset',
                lead: [first, second],
                rail_hidden: TODAY_RAIL_DEFAULT_HIDDEN,
                customized: false,
                person_hidden: TODAY_RAIL_DEFAULT_HIDDEN,
            },
        ])
    })
})
