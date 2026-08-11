import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { settingsLogic } from './settingsLogic'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

describe('settingsLogic', () => {
    let scrollTo: jest.Mock

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        scrollTo = jest.fn()
        jest.spyOn(document, 'querySelector').mockImplementation((selector: string) =>
            selector === 'main' ? ({ scrollTo } as unknown as Element) : null
        )
    })

    afterEach(() => {
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('scrolls the content pane to the top on selectSetting when embedded in a section', () => {
        const logic = settingsLogic({ logicKey: 'replaySettings', sectionId: 'environment-replay' })
        logic.mount()

        logic.actions.selectSetting('replay-ingestion')
        jest.runOnlyPendingTimers()

        expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
    })

    it('does not scroll on selectSetting in the standalone settings scene (no sectionId)', async () => {
        const logic = settingsLogic({ logicKey: 'settingsScene' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.selectSetting('replay-ingestion')
        }).toMatchValues({ selectedSettingId: 'replay-ingestion' })
        jest.runOnlyPendingTimers()

        expect(scrollTo).not.toHaveBeenCalled()
    })
})
