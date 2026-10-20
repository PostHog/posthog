import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'

import { AccessControlLevel, AccessControlResourceType, type AppContext } from '~/types'

import { getEvaluationsEntryRedirect } from './evaluationsEntryRedirect'

describe('Evaluations product entry', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    afterEach(() => {
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it.each([
        [AccessControlLevel.None, AccessControlLevel.Viewer, '/ai-evals/evaluations/scorers', false],
        [AccessControlLevel.Viewer, AccessControlLevel.None, null, false],
        [AccessControlLevel.None, AccessControlLevel.None, '/ai-evals/evaluations/scorers', true],
    ])(
        'keeps the product entry aligned with resource access: %s / %s',
        (evaluationAccess, scorerAccess, redirect, disabled) => {
            window.POSTHOG_APP_CONTEXT = {
                ...priorAppContext,
                effective_resource_access_control: {
                    [AccessControlResourceType.Evaluation]: evaluationAccess,
                    [AccessControlResourceType.LlmAnalytics]: scorerAccess,
                },
            } as AppContext

            expect(getEvaluationsEntryRedirect({})).toBe(redirect)
            expect(Boolean(getProductAccessDisabledReason({ sceneKey: Scene.AIObservabilityEvaluations }))).toBe(
                disabled
            )
        }
    )

    it.each(['offline', 'offline-evals'])('moves legacy offline tab links before online setup: %s', (tab) => {
        expect(getEvaluationsEntryRedirect({ tab })).toBe('/ai-evals/evaluations/offline/experiments')
        expect(getEvaluationsEntryRedirect({ tab, experiment: 'experiment-1' })).toBe(
            '/ai-evals/evaluations/offline/experiments/experiment-1'
        )
    })
})
