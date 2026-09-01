import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

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

    it.each([
        ['reports a genuine server error', new Error('A server error occurred.'), true],
        ['stays quiet on a transient gateway error', new ApiError('Bad gateway', 502), false],
    ])(
        'treats a failed snippet-events check as no events yet, without a failure, and %s',
        async (_, error, reported) => {
            const captureExceptionSpy = jest
                .spyOn(posthog, 'captureException')
                .mockImplementation(() => undefined as any)
            jest.spyOn(api, 'queryHogQL').mockRejectedValue(error)

            await expectLogic(logic, () => {
                logic.actions.loadSnippetEvents()
            })
                .toDispatchActions(['loadSnippetEvents', 'loadSnippetEventsSuccess'])
                .toNotHaveDispatchedActions(['loadSnippetEventsFailure'])
                .toMatchValues({ hasSnippetEvents: false })

            if (reported) {
                expect(captureExceptionSpy).toHaveBeenCalledWith(error)
            } else {
                expect(captureExceptionSpy).not.toHaveBeenCalled()
            }
        }
    )
})
