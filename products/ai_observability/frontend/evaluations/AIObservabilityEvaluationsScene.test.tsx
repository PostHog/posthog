import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AIObservabilityEvaluationsScene } from './AIObservabilityEvaluationsScene'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'

describe('AIObservabilityEvaluationsScene', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/projects/:teamId/evaluations/': { results: [] },
                '/api/projects/:teamId/evaluation_directories/': [],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('releases the evaluations logic when the scene exits, so the next visit refetches', () => {
        const evaluationsLogic = llmEvaluationsLogic()
        const unmountSceneLogic = evaluationsLogic.mount() // what SceneExport.logic does

        const { unmount } = render(
            <Provider>
                <AIObservabilityEvaluationsScene />
            </Provider>
        )

        unmount()
        unmountSceneLogic()

        expect(evaluationsLogic.isMounted()).toBe(false)
    })
})
