import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todaySpacesLogic } from './todaySpacesLogic'

describe('todaySpacesLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const channel = new URL(request.url).searchParams.get('channel')
                    if (channel === 'space-broken') {
                        return [500, { detail: 'Server error' }]
                    }
                    return [200, { results: [{ id: `task-${channel}`, title: `Session in ${channel}` }], count: 1 }]
                },
            },
        })
        initKeaTests()
    })

    it('keeps the sessions of every space expanded at the same time', async () => {
        const logic = todaySpacesLogic()
        logic.mount()

        logic.actions.toggleSpace('space-a')
        logic.actions.toggleSpace('space-b')
        await expectLogic(logic).toFinishAllListeners()

        expect(Object.keys(logic.values.spaceTasks).sort()).toEqual(['space-a', 'space-b'])
        expect(logic.values.spaceTasks['space-a'][0].id).toBe('task-space-a')
        expect(logic.values.loadingSpaceIds).toEqual([])
    })

    it('marks a space whose sessions fail to load, so the sidebar can offer a retry', async () => {
        const logic = todaySpacesLogic()
        logic.mount()

        logic.actions.toggleSpace('space-broken')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.failedSpaceIds).toEqual(['space-broken'])
        expect(logic.values.spaceTasks['space-broken']).toBeUndefined()
    })
})
