import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BRIEFING_POLL_MS, todayBriefingLogic } from './todayBriefingLogic'
import { makeBriefing } from './todayTestFixtures'

describe('todayBriefingLogic', () => {
    let briefingResponses: [number, any][]
    let briefingCalls: number

    beforeEach(() => {
        briefingResponses = []
        briefingCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/today/briefing/': () => {
                    briefingCalls += 1
                    return briefingResponses.length > 1 ? briefingResponses.shift()! : briefingResponses[0]
                },
            },
            post: {
                '/api/projects/:team_id/today/briefing/refresh/': () => [
                    200,
                    makeBriefing({ id: 'b-next', status: 'writing' }),
                ],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('keeps the last briefing on screen, polls while the next is written, and stops when it is ready', async () => {
        jest.useFakeTimers()
        const previous = makeBriefing({ id: 'b-previous', status: 'writing' })
        const ready = makeBriefing()
        briefingResponses = [
            [200, previous],
            [200, ready],
        ]
        const logic = todayBriefingLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadPersonalBriefing()
        })
            .toDispatchActions(['loadPersonalBriefingSuccess'])
            .toMatchValues({ briefingWaiting: true, personalBriefing: previous })

        await expectLogic(logic, () => {
            jest.advanceTimersByTime(BRIEFING_POLL_MS)
        })
            .toDispatchActions(['pollBriefing', 'loadPersonalBriefingSuccess'])
            .toMatchValues({ briefingWaiting: false, personalBriefing: ready })

        await jest.advanceTimersByTimeAsync(BRIEFING_POLL_MS * 3)
        expect(briefingCalls).toBe(2)
    })

    it('keeps waiting from the refresh click until the reloaded briefing says it is written', async () => {
        const shown = makeBriefing()
        briefingResponses = [
            [200, shown],
            [200, { ...shown, status: 'writing' }],
        ]
        const logic = todayBriefingLogic()
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.loadPersonalBriefing()
        })
            .toDispatchActions(['loadPersonalBriefingSuccess'])
            .toMatchValues({ briefingWaiting: false })

        await expectLogic(logic, () => {
            logic.actions.refreshBriefing()
        })
            .toDispatchActions(['refreshBriefing', 'refreshBriefingSuccess'])
            .toMatchValues({ briefingWaiting: true })
            .toDispatchActions(['loadPersonalBriefing', 'loadPersonalBriefingSuccess'])
            .toMatchValues({ briefingWaiting: true })
    })
})
