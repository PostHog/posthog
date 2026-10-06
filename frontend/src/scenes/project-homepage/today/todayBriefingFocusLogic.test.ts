import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { FocusTopicApi } from 'products/today/frontend/generated/api.schemas'

import { todayBriefingFocusLogic } from './todayBriefingFocusLogic'

describe('todayBriefingFocusLogic', () => {
    let logic: ReturnType<typeof todayBriefingFocusLogic.build>
    let saved: FocusTopicApi[]
    let putStatus: number

    beforeEach(() => {
        saved = [{ topic: 'logs', direction: 'more' }]
        putStatus = 200
        useMocks({
            get: { '/api/projects/:team_id/today/focus/': () => [200, { topics: saved }] },
            put: {
                '/api/projects/:team_id/today/focus/': async ({ request }) => {
                    if (putStatus !== 200) {
                        return [putStatus, { detail: 'Not found.' }]
                    }
                    saved = ((await request.json()) as { topics: FocusTopicApi[] }).topics
                    return [200, { topics: saved }]
                },
            },
        })
        initKeaTests()
        logic = todayBriefingFocusLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('saves a steer, replaces the other direction, and takes the topic out on a second press', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.steerTopic('surveys', 'more')
        logic.actions.steerTopic('surveys', 'less')
        await expectLogic(logic).toFinishAllListeners()
        expect(saved).toEqual([
            { topic: 'logs', direction: 'more' },
            { topic: 'surveys', direction: 'less' },
        ])

        logic.actions.steerTopic('surveys', 'less')
        await expectLogic(logic).toFinishAllListeners()
        expect(saved).toEqual([{ topic: 'logs', direction: 'more' }])
    })

    it('puts the saved focus back on screen when a save fails', async () => {
        await expectLogic(logic).toFinishAllListeners()
        putStatus = 404

        await expectLogic(logic, () => logic.actions.removeTopic('logs'))
            .toMatchValues({ topics: [] })
            .toDispatchActions(['saveTopicsFailure', 'loadFocusSuccess'])
            .toMatchValues({ topics: [{ topic: 'logs', direction: 'more' }] })
    })
})
