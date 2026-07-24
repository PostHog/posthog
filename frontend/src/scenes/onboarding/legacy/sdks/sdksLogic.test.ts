import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    ErrorTrackingSDKDocsLinkOverrides,
    ErrorTrackingSDKInstructions,
} from './error-tracking/ErrorTrackingSDKInstructions'
import { sdksLogic } from './sdksLogic'

describe('sdksLogic', () => {
    let logic: ReturnType<typeof sdksLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
        logic = sdksLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    const configureErrorTrackingSDKs = (): void => {
        logic.actions.setSDKDocsLinkOverrides(ErrorTrackingSDKDocsLinkOverrides)
        logic.actions.setAvailableSDKInstructionsMap(ErrorTrackingSDKInstructions)
    }

    it.each([
        ['before', false],
        ['after', true],
    ])('applies product docs overrides when the URL selects an SDK %s configuration', async (_, configureFirst) => {
        if (configureFirst) {
            configureErrorTrackingSDKs()
        }

        await expectLogic(logic, () => {
            router.actions.push('/onboarding/error_tracking?sdk=convex')
        }).toDispatchActions(['setSelectedSDK'])

        if (!configureFirst) {
            configureErrorTrackingSDKs()
        }

        expect(logic.values.selectedSDK?.docsLink).toBe('https://posthog.com/docs/libraries/convex')
    })
})
