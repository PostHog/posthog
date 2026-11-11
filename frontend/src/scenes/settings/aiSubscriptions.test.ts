import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { settingsLogic } from './settingsLogic'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

describe('AI subscription settings access', () => {
    afterEach(() => {
        delete window.POSTHOG_APP_CONTEXT!.posthog_ai_access
    })
    it.each([
        [true, true, false, true],
        [true, false, false, false],
        [false, true, false, false],
        [false, false, false, false],
        [undefined, true, false, false],
        [false, true, true, false],
    ])(
        'AI access=%s, subscription flag=%s, sandbox flag=%s, visible=%s',
        (hasAccess, subscriptionEnabled, sandboxEnabled, visible) => {
            initKeaTests()
            window.POSTHOG_APP_CONTEXT!.posthog_ai_access = hasAccess
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: sandboxEnabled,
                [FEATURE_FLAGS.POSTHOG_CODE_CODEX_OWN_SUBSCRIPTION_CLOUD]: subscriptionEnabled,
            })
            const logic = settingsLogic({ logicKey: 'ai-subscription-test', sectionId: 'environment-ai-subscriptions' })
            logic.mount()
            const sectionId = 'environment-ai-subscriptions'.replace('environment-', 'project-')

            for (const todayEnabled of [true, false]) {
                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayEnabled,
                    [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: sandboxEnabled,
                    [FEATURE_FLAGS.POSTHOG_CODE_CODEX_OWN_SUBSCRIPTION_CLOUD]: subscriptionEnabled,
                })
                expect(logic.values.unavailableSection).toBeNull()
                expect(logic.values.selectedSection !== null).toBe(visible)
                expect(logic.values.sections.some(({ id }) => id === sectionId)).toBe(visible)
                expect(logic.values.settings.some(({ id }) => id === 'ai-subscription-codex')).toBe(visible)
                expect(
                    logic.values.globalSearchIndex
                        .search('Codex')
                        .some(({ item }) => item.settingId === 'ai-subscription-codex')
                ).toBe(visible)
            }
            logic.unmount()
        }
    )
})
