import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, test } from 'node:test'

import {
    affectedStoriesFor,
    loadTimings,
    requiresFullRun,
    suggestShards,
    unresolvedRuntimeFiles,
    workloadSeconds,
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

    // A selective run that gets too few shards spends more wall time on its short
    // story list than a full run spends on all of them, which makes the narrowed
    // run the slow lane it was meant to avoid.
    test('sizes a narrowed run to the shard density of the full matrix', () => {
        // Half the story seconds of the full matrix, so half its shards.
        assert.equal(suggestShards(5000, 10000, 28), 14)
        // A change set that touches every story must not ask for more than the full matrix.
        assert.equal(suggestShards(10000, 10000, 28), 28)
        assert.equal(suggestShards(20000, 10000, 28), 28)
        // A heavy dozen stories still earns more than a single shard.
        assert.equal(suggestShards(2000, 10000, 28), 6)
        assert.equal(suggestShards(10, 10000, 28), 1)
    })

    test('reads chromium times from the manifest and rejects unusable files', () => {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'story-timings-'))
        const good = path.join(dir, 'good.json')
        fs.writeFileSync(
            good,
            JSON.stringify({
                'frontend/src/A.stories.tsx': { chromium: 10, webkit: 3 },
                'frontend/src/B.stories.tsx': { webkit: 4 },
            })
        )
        const timings = loadTimings(good)
        assert.deepEqual([...timings.keys()], ['frontend/src/A.stories.tsx'])

        const list = path.join(dir, 'list.json')
        fs.writeFileSync(list, '[]')
        assert.equal(loadTimings(list), null)
        assert.equal(loadTimings(path.join(dir, 'missing.json')), null)
    })

    test('costs an untimed story the manifest median', () => {
        const timings = new Map([
            ['a.stories.tsx', { chromium: 10 }],
            ['b.stories.tsx', { chromium: 20 }],
            ['c.stories.tsx', { chromium: 90 }],
        ])
        assert.equal(workloadSeconds(['a.stories.tsx', 'c.stories.tsx'], timings), 100)
        // Not in the manifest, so it costs the median of 10, 20, 90.
        assert.equal(workloadSeconds(['new.stories.tsx'], timings), 20)
        // No manifest at all falls back to the flat per-story estimate.
        assert.equal(workloadSeconds(['a.stories.tsx', 'b.stories.tsx'], null), 12)
    })
})
