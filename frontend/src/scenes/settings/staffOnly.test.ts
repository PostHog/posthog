import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { settingsLogic } from './settingsLogic'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

describe('staffOnly settings', () => {
    it.each([
        [true, true],
        [false, false],
    ])('is_staff=%s shows AI gateway developer mode: %s', (isStaff, visible) => {
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })
        const logic = settingsLogic({ logicKey: 'staff-only-test', sectionId: 'user-ai-gateway-dev-mode' })
        logic.mount()

        expect(logic.values.sections.some((section) => section.id === 'user-ai-gateway-dev-mode')).toBe(visible)
        expect(logic.values.settings.some((setting) => setting.id === 'ai-gateway-dev-mode')).toBe(visible)
        expect(
            logic.values.globalSearchIndex
                .search('developer mode')
                .some(({ item }) => item.settingId === 'ai-gateway-dev-mode')
        ).toBe(visible)
    })
})
