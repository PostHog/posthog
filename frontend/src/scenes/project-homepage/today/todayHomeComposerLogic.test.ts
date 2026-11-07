import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { todayHomeComposerLogic } from './todayHomeComposerLogic'

describe('todayHomeComposerLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('opens the task that the home composer started', () => {
        const logic = todayHomeComposerLogic()
        logic.mount()

        logic.actions.homeTaskStarted('task-1')

        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(router.values.searchParams).toMatchObject({ task: 'task-1' })
    })
})
