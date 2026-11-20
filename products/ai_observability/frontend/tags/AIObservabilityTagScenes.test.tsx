import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TaggerApi } from '../generated/api.schemas'
import { scene as tagScene } from './AIObservabilityTagScene'
import { scene as tagsScene } from './AIObservabilityTagsScene'
import { llmTaggerLogic } from './llmTaggerLogic'
import { llmTaggersLogic } from './llmTaggersLogic'

const tagger: TaggerApi = {
    id: 'tagger-1',
    name: 'Test tagger',
    description: '',
    enabled: false,
    tagger_type: 'hog',
    tagger_config: { source: 'return []', tags: [] },
    conditions: [],
    model_configuration: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    created_by: { id: 1, uuid: 'user-1', email: 'test@example.com', hedgehog_config: null },
    deleted: false,
    migrated_to_evaluation_id: null,
}

describe('tagger scene access', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:teamId/taggers/': { results: [] },
                '/api/projects/:teamId/taggers/:id/': tagger,
            },
            post: {
                '/api/environments/:teamId/query/:kind': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([
        { name: 'list', scene: tagsScene, buildLogic: () => llmTaggersLogic(), loadedText: 'No taggers found.' },
        {
            name: 'detail',
            scene: tagScene,
            buildLogic: () => llmTaggerLogic({ id: tagger.id }),
            loadedText: tagger.name,
        },
    ])(
        'loads the $name page only while the resolved feature flag is enabled',
        async ({ scene, buildLogic, loadedText }) => {
            const getSpy = jest.spyOn(api, 'get')
            const dataRequests = (): string[] =>
                getSpy.mock.calls.map(([url]) => url).filter((url) => url.includes('/taggers/'))
            const props = scene.paramsToProps?.({ params: { id: tagger.id }, searchParams: {}, hashParams: {} }) || {}
            // The router mounts SceneExport.logic before rendering the component.
            const unmountSceneLogic = scene.logic?.(props).mount()
            const Component = scene.component!
            const logic = buildLogic()

            try {
                render(
                    <Provider>
                        <Component {...props} />
                    </Provider>
                )

                expect(logic.isMounted()).toBe(false)
                expect(dataRequests()).toEqual([])
                expect(screen.queryByText('Taggers are not enabled for this project.')).not.toBeInTheDocument()

                act(() => featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.LLM_ANALYTICS_TAGS]: false }))

                expect(screen.getByText('Taggers are not enabled for this project.')).toBeInTheDocument()
                expect(logic.isMounted()).toBe(false)
                expect(dataRequests()).toEqual([])

                act(() =>
                    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LLM_ANALYTICS_TAGS], {
                        [FEATURE_FLAGS.LLM_ANALYTICS_TAGS]: true,
                    })
                )

                await screen.findByText(loadedText)
                await waitFor(() => expect(dataRequests().some((url) => url.includes('/taggers/'))).toBe(true))
                expect(logic.isMounted()).toBe(true)
                expect(screen.queryByText('Taggers are not enabled for this project.')).not.toBeInTheDocument()

                act(() => featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.LLM_ANALYTICS_TAGS]: false }))

                expect(screen.getByText('Taggers are not enabled for this project.')).toBeInTheDocument()
                expect(logic.isMounted()).toBe(false)
            } finally {
                unmountSceneLogic?.()
            }
        }
    )
})
