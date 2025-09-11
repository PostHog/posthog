import { expectLogic } from 'kea-test-utils'

import { miniFiltersLogic } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { initKeaTests } from '~/test/init'

describe('miniFiltersLogic', () => {
    let logic: ReturnType<typeof miniFiltersLogic.build>
    let eventLogic: ReturnType<typeof sessionRecordingEventUsageLogic.build>

    beforeEach(() => {
        initKeaTests()
        eventLogic = sessionRecordingEventUsageLogic()
        eventLogic.mount()
        logic = miniFiltersLogic()
        logic.mount()
    })
    describe('initialState', () => {
        it('sets default values', () => {
            expectLogic(logic).toMatchValues({
                showOnlyMatching: false,
                selectedMiniFilters: [
                    'events-posthog',
                    'events-custom',
                    'events-pageview',
                    'events-autocapture',
                    'events-exceptions',
                    'console-info',
                    'console-warn',
                    'console-error',
                    'comment',
                ],
            })
        })
    })

    describe('setShowOnlyMatching', () => {
        it('start as false', async () => {
            await expectLogic(logic).toMatchValues({
                showOnlyMatching: false,
            })
        })
        it('happy case', async () => {
            await expectLogic(logic, () => {
                logic.actions.setShowOnlyMatching(true)
            })
                .toDispatchActions(['setShowOnlyMatching'])
                .toMatchValues({
                    showOnlyMatching: true,
                })
        })
    })

    describe('miniFilters', () => {
        afterEach(() => {
            localStorage.clear()
        })

        it('can unselect', async () => {
            await expectLogic(logic, () => {
                logic.actions.setMiniFilter('events-posthog', false)
            }).toMatchValues({
                selectedMiniFilters: [
                    'events-custom',
                    'events-pageview',
                    'events-autocapture',
                    'events-exceptions',
                    'console-info',
                    'console-warn',
                    'console-error',
                    'comment',
                ],
            })
        })
    })
})
