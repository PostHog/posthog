import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { ReplayTabs } from '~/types'

import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { playerSettingsLogic } from './playerSettingsLogic'

describe('playerSettingsLogic', () => {
    let logic: ReturnType<typeof playerSettingsLogic.build>
    let eventLogic: ReturnType<typeof sessionRecordingEventUsageLogic.build>

    beforeEach(() => {
        localStorage.clear()
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
    describe('URL handling', () => {
        const home = urls.replay(ReplayTabs.Home)
        const watchLayout = (): void =>
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.REPLAY_WATCH_LAYOUT]: 'compact' })
        const openLink = (path: string, searchParams = {}, hashParams = {}): void => {
            logic.unmount()
            router.actions.push(path, searchParams, hashParams)
            logic.mount()
        }

        beforeEach(() => {
            featureFlagLogic.mount()
        })

        it.each([
            ['search', { inspectorSideBar: true }, {}],
            ['hash', {}, { inspectorSideBar: true }],
        ])('an old inspectorSideBar %s link opens Debug once', (_, searchParams, hashParams) => {
            watchLayout()
            openLink(home, searchParams, hashParams)
            expect(logic.values.debugMode).toBe(true)

            logic.actions.setDebugMode(false)
            expect(router.values.searchParams.inspectorSideBar).toBeUndefined()
            expect(router.values.hashParams.inspectorSideBar).toBeUndefined()

            router.actions.push(home, router.values.searchParams, router.values.hashParams)
            expect(logic.values.debugMode).toBe(false)
        })

        it('an old inspectorSideBar link waits for the flags before opening Debug', () => {
            openLink(home, { inspectorSideBar: true })
            expect(logic.values.debugMode).toBe(false)
            watchLayout()
            expect(logic.values.debugMode).toBe(true)
        })

        it('an old inspectorSideBar link leaves Debug off in the classic layout', () => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            openLink(home, { inspectorSideBar: true })
            expect(logic.values.sidebarOpen).toBe(true)
            expect(logic.values.debugMode).toBe(false)
        })

        it('an old inspectorSideBar link to another page leaves Debug off', () => {
            watchLayout()
            openLink(urls.replaySingle('1'), { inspectorSideBar: true })
            expect(logic.values.sidebarOpen).toBe(true)
            expect(logic.values.debugMode).toBe(false)
        })

        it('opening the classic sidebar leaves Debug off', () => {
            watchLayout()
            openLink(home)
            logic.actions.setSidebarOpen(true)
            expect(router.values.searchParams.inspectorSideBar).toBe(true)
            expect(logic.values.debugMode).toBe(false)
        })

        it('the classic sidebar param carried onto the next recording leaves Debug off', () => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            openLink(home)
            logic.actions.setSidebarOpen(true)
            watchLayout()
            router.actions.push(home, { ...router.values.searchParams, sessionRecordingId: '2' })
            expect(logic.values.debugMode).toBe(false)
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
})
