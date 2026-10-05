import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import {
    affectedStoriesFor,
    estimateDuration,
    requiresFullRun,
    suggestShards,
    unresolvedRuntimeFiles,
} from './find-affected-stories'

describe('find-affected-stories', () => {
    const graph = {
        byName: new Map([
            [
                'frontend/src/scenes/experiments/experimentLogic.ts',
                {
                    name: 'frontend/src/scenes/experiments/experimentLogic.ts',
                    reasons: ['frontend/src/scenes/experiments/Experiment.tsx'],
                },
            ],
            [
                'frontend/src/scenes/experiments/Experiment.tsx',
                {
                    name: 'frontend/src/scenes/experiments/Experiment.tsx',
                    reasons: ['frontend/src/scenes/experiments/stories/Experiments.stories.tsx'],
                },
            ],
            [
                'frontend/src/scenes/experiments/stories/Experiments.stories.tsx',
                { name: 'frontend/src/scenes/experiments/stories/Experiments.stories.tsx', reasons: [] },
            ],
            [
                'frontend/src/scenes/data-warehouse/editor/SqlEditor.stories.tsx',
                { name: 'frontend/src/scenes/data-warehouse/editor/SqlEditor.stories.tsx', reasons: [] },
            ],
        ]),
    }

    test('selects only stories that transitively import a feature-local change', () => {
        const result = affectedStoriesFor(['frontend/src/scenes/experiments/experimentLogic.ts'], graph)

        assert.deepEqual(result.affected, ['frontend/src/scenes/experiments/stories/Experiments.stories.tsx'])
    })

    test('requires a full run for shared frontend library changes', () => {
        assert.match(requiresFullRun('frontend/src/lib/lemon-ui/LemonButton.tsx'), /frontend\/src\/lib\//)
    })

    test('treats unresolved runtime frontend files as unsafe to skip', () => {
        assert.deepEqual(unresolvedRuntimeFiles(['frontend/src/scenes/experiments/newLogic.ts']), [
            'frontend/src/scenes/experiments/newLogic.ts',
        ])
    })

    test('sizes selective shards from the measured render time of the affected story files', () => {
        const timings = {
            'frontend/src/scenes/max/Max.stories.tsx': 176,
            'frontend/src/scenes/experiments/stories/Experiments.stories.tsx': 40,
            'frontend/src/scenes/data-warehouse/editor/SqlEditor.stories.tsx': 10,
        }

        assert.equal(
            estimateDuration(
                ['frontend/src/scenes/max/Max.stories.tsx', 'frontend/src/scenes/new/New.stories.tsx'],
                timings
            ),
            216
        )
        assert.equal(suggestShards(0), 1)
        assert.equal(suggestShards(estimateDuration(Object.keys(timings), timings)), 1)
        assert.equal(suggestShards(8 * 60 * 3 + 1), 4)
    })

    test('ignores unresolved backend, test, and README files', () => {
        assert.deepEqual(
            unresolvedRuntimeFiles([
                'products/experiments/backend/api.py',
                'frontend/src/scenes/experiments/experimentLogic.test.ts',
                'frontend/src/scenes/experiments/README.md',
            ]),
            []
        )
    })
})
