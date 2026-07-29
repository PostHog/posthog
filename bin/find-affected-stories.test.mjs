import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import {
    affectedStoriesFor,
    requiresFullRun,
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
