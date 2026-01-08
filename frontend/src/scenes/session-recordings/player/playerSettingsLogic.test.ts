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
    describe('setSkipInactivitySetting', () => {
        it('sets the skip inactivity setting', () => {
            expectLogic(logic, () => {
                logic.actions.setSkipInactivitySetting(false)
            }).toMatchValues({ skipInactivitySetting: false })
        })
    })

    describe('exporter URL parameters', () => {
        it('sets skipInactivitySetting to true when showMetadataFooter is true', async () => {
            router.actions.push('/recordings/exporter', { showMetadataFooter: true })
            await expectLogic(logic).toFinishAllListeners()
            expectLogic(logic).toMatchValues({
                skipInactivitySetting: true,
                showMetadataFooter: true,
            })
        })

        it('sets skipInactivitySetting to false when showMetadataFooter is false', async () => {
            router.actions.push('/recordings/exporter', { showMetadataFooter: false })
            await expectLogic(logic).toFinishAllListeners()
            expectLogic(logic).toMatchValues({
                skipInactivitySetting: false,
                showMetadataFooter: false,
            })
        })

        it('sets skipInactivitySetting to false when showMetadataFooter is not provided', async () => {
            router.actions.push('/recordings/exporter')
            await expectLogic(logic).toFinishAllListeners()
            expectLogic(logic).toMatchValues({
                skipInactivitySetting: false,
                showMetadataFooter: false,
            })
        })

        it('sets player speed from URL parameter', async () => {
            router.actions.push('/recordings/exporter', { playerSpeed: '2' })
            await expectLogic(logic).toFinishAllListeners()
            expectLogic(logic).toMatchValues({
                speed: 2,
            })
        })

        it('sets player speed to default when not provided', async () => {
            router.actions.push('/recordings/exporter')
            await expectLogic(logic).toFinishAllListeners()
            expectLogic(logic).toMatchValues({
                speed: 1,
            })
        })

        it('sets both speed and metadata footer from URL parameters', async () => {
            router.actions.push('/recordings/exporter', { playerSpeed: '4', showMetadataFooter: true })
            await expectLogic(logic).toFinishAllListeners()
            expectLogic(logic).toMatchValues({
                speed: 4,
                skipInactivitySetting: true,
                showMetadataFooter: true,
            })
        })
    })
})
