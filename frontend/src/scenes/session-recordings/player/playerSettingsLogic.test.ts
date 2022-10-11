import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { playerSettingsLogic } from './playerSettingsLogic'

describe('playerSettingsLogic', () => {
    let logic: ReturnType<typeof playerSettingsLogic.build>

    beforeEach(() => {
        initKeaTests()
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
})
