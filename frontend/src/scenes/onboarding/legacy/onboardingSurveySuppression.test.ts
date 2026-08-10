import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { onboardingLogic } from './onboardingLogic'

describe('onboardingLogic — survey suppression', () => {
    let logic: ReturnType<typeof onboardingLogic.build>

    beforeEach(() => {
        initKeaTests()
        ;(posthog as any).config = { disable_surveys: false }
        ;(posthog.set_config as jest.Mock).mockImplementation((partial: Record<string, unknown>) => {
            Object.assign((posthog as any).config, partial)
        })
        logic = onboardingLogic()
    })

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
    })

    it('suppresses surveys while onboarding is mounted and restores the prior value on leave', () => {
        logic.mount()
        expect(posthog.config.disable_surveys).toBe(true)

        logic.unmount()
        expect(posthog.config.disable_surveys).toBe(false)
    })
})
