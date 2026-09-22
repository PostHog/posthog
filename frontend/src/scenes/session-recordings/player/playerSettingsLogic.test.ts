import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { playerSettingsLogic } from './playerSettingsLogic'

describe('playerSettingsLogic', () => {
    let logic: ReturnType<typeof playerSettingsLogic.build>
    let eventLogic: ReturnType<typeof sessionRecordingEventUsageLogic.build>

    beforeEach(() => {
        initKeaTests()
        eventLogic = sessionRecordingEventUsageLogic()
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
    describe('exporter playerSpeed', () => {
        // speed reaches rrweb, the seek jump distance and a persisted reducer, so an unusable one
        // from a shared exporter URL froze playback until storage was cleared.
        it.each([
            ['4', 4],
            ['0', 1],
            ['-2', 1],
            ['abc', 1],
            ['', 1],
        ])('resolves ?playerSpeed=%s to %s', (param, expected) => {
            router.actions.push(`/exporter?playerSpeed=${param}`)

            expectLogic(logic).toMatchValues({ speed: expected })
        })
    })

    describe('setSkipInactivitySetting', () => {
        it('sets the skip inactivity setting', () => {
            expectLogic(logic, () => {
                logic.actions.setSkipInactivitySetting(false)
            }).toMatchValues({ skipInactivitySetting: false })
        })
    })
})
