import { expectLogic } from 'kea-test-utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { initKeaTests } from '~/test/init'

import { playerSettingsLogic } from './playerSettingsLogic'

describe('playerSettingsLogic', () => {
    let logic: ReturnType<typeof playerSettingsLogic.build>
    let eventLogic: ReturnType<typeof eventUsageLogic.build>

    beforeEach(() => {
        initKeaTests()
        eventLogic = eventUsageLogic()
        eventLogic.mount()
        logic = playerSettingsLogic()
        logic.mount()
    })
    describe('initialState', () => {
        it('sets default values', () => {
            expectLogic(logic).toMatchValues({
                speed: 1,
                skipInactivitySetting: true,
            })
        })
    })
    describe('setSpeed', () => {
        it('sets the speed', () => {
            expectLogic(logic, () => {
                logic.actions.setSpeed(4)
            }).toMatchValues({ speed: 4 })
        })
    })
    describe('setSkipInactivitySetting', () => {
        it('sets the skip inactivity setting', () => {
            expectLogic(logic, () => {
                logic.actions.setSkipInactivitySetting(false)
            }).toMatchValues({ skipInactivitySetting: false })
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
        it('should start with the first entry selected', () => {
            expect(logic.values.selectedMiniFilters).toEqual([
                'all-automatic',
                'console-all',
                'events-all',
                'performance-all',
            ])
        })

        it('should remove other selected filters if alone', () => {
            logic.actions.setMiniFilter('all-errors', true)

            expect(logic.values.selectedMiniFilters.sort()).toEqual([
                'all-errors',
                'console-all',
                'events-all',
                'performance-all',
            ])
        })

        it('should allow multiple filters if not alone', () => {
            logic.actions.setMiniFilter('console-warn', true)
            logic.actions.setMiniFilter('console-info', true)

            expect(logic.values.selectedMiniFilters.sort()).toEqual([
                'all-automatic',
                'console-info',
                'console-warn',
                'events-all',
                'performance-all',
            ])
        })

        it('should reset to first in tab if empty', () => {
            expect(logic.values.selectedMiniFilters.sort()).toEqual([
                'all-automatic',
                'console-all',
                'events-all',
                'performance-all',
            ])
            logic.actions.setMiniFilter('console-warn', true)
            logic.actions.setMiniFilter('console-info', true)

            expect(logic.values.selectedMiniFilters.sort()).toEqual([
                'all-automatic',
                'console-info',
                'console-warn',
                'events-all',
                'performance-all',
            ])

            logic.actions.setMiniFilter('console-warn', false)
            logic.actions.setMiniFilter('console-info', false)

            expect(logic.values.selectedMiniFilters.sort()).toEqual([
                'all-automatic',
                'console-all',
                'events-all',
                'performance-all',
            ])
        })
    })
})
