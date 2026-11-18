import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { evaluationsEntryLogic } from './evaluationsEntryLogic'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'

describe('evaluationsEntryLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/projects/:teamId/evaluations/': { results: [] },
                '/api/projects/:teamId/evaluation_directories/': [],
            },
        })
        initKeaTests()
    })

    it.each([
        ['starts', {}, true],
        ['skips', { tab: 'offline' }, false],
    ])('%s the evaluations list reads for %p', (_, searchParams, mounted) => {
        router.actions.push(urls.aiObservabilityEvaluations(), searchParams)
        const logic = evaluationsEntryLogic()
        logic.mount()
        expect(llmEvaluationsLogic.isMounted()).toBe(mounted)

        logic.unmount()
        expect(llmEvaluationsLogic.isMounted()).toBe(false)
    })
})
