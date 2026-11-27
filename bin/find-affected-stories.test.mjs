import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, test } from 'node:test'

import {
    affectedStoriesFor,
    loadTimings,
    modulesLoadedByEveryStory,
    requiresFullRun,
    suggestShards,
    unboundedChangeReason,
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

    describe('shared library changes', () => {
        const preview = 'common/storybook/.storybook/preview.tsx'
        const decorator = 'common/storybook/.storybook/decorators/withKea/kea-story.tsx'
        const button = 'frontend/src/lib/lemon-ui/LemonButton/LemonButton.tsx'
        const app = 'frontend/src/scenes/App.tsx'
        const lazyScene = 'frontend/src/scenes/experiments/Experiment.tsx'
        const dateFilter = 'frontend/src/lib/components/DateFilter/DateFilter.tsx'
        const dateFilterStory = 'frontend/src/lib/components/DateFilter/DateFilter.stories.tsx'
        const modules = [
            { name: preview, reasons: [], dynamicReasons: [] },
            { name: decorator, reasons: [preview], dynamicReasons: [] },
            { name: app, reasons: [decorator], dynamicReasons: [] },
            { name: button, reasons: [app, lazyScene], dynamicReasons: [] },
            { name: lazyScene, reasons: [app], dynamicReasons: [app] },
            { name: dateFilter, reasons: [lazyScene, dateFilterStory], dynamicReasons: [] },
            { name: dateFilterStory, reasons: [], dynamicReasons: [] },
        ]
        const libGraph = { byName: new Map(modules.map((m) => [m.name, m])) }
        const withoutImportKinds = modules.map(({ name, reasons }) => ({ name, reasons }))

        test('narrows a library component the preview reaches only through a lazy scene', () => {
            const loaded = modulesLoadedByEveryStory(modules)
            assert.equal(requiresFullRun(dateFilter), null)
            assert.equal(unboundedChangeReason(dateFilter, libGraph, loaded), null)
            assert.deepEqual(affectedStoriesFor([dateFilter], libGraph).affected, [dateFilterStory])
        })

        test('requires a full run for a module the preview imports statically', () => {
            const loaded = modulesLoadedByEveryStory(modules)
            assert.match(unboundedChangeReason(button, libGraph, loaded), /loaded by the Storybook preview/)
            assert.match(unboundedChangeReason(app, libGraph, loaded), /loaded by the Storybook preview/)
        })

        test('falls back to a full run for library modules when the graph has no import kinds', () => {
            assert.equal(modulesLoadedByEveryStory(withoutImportKinds), null)
            assert.match(unboundedChangeReason(dateFilter, libGraph, null), /frontend\/src\/lib\//)
            assert.equal(unboundedChangeReason('frontend/src/lib/components/owners.yaml', libGraph, null), null)
            assert.equal(unboundedChangeReason(lazyScene, libGraph, null), null)
        })
    })

    test('treats unresolved runtime frontend files as unsafe to skip', () => {
        const unsafe = [
            'frontend/src/scenes/experiments/newLogic.ts',
            'frontend/src/lib/components/ProductEmptyState/_previewMixins.scss',
            'frontend/src/lib/elkWorker.ts',
            'frontend/bin/watch-workers.mjs',
            'frontend/public/notes.md',
            'frontend/plugins/vite-zod-jitless-plugin.ts',
            'common/storybook/test-runner-jest.config.js',
            'common/storybook/test-sequencer.js',
            'frontend/src/lib/components/DomainConnect/templates/posthog.com.reverse-proxy-eu.json',
            'products/dashboards/frontend/generated/widget-config-property-keys.json',
            'services/mcp/src/ui-apps/apps/generated/action.tsx',
        ]
        assert.deepEqual(unresolvedRuntimeFiles(unsafe), unsafe)
    })

    test('ignores unresolved backend, test, docs, ownership, tooling, and generated API type files', () => {
        assert.deepEqual(
            unresolvedRuntimeFiles([
                'products/experiments/backend/api.py',
                'frontend/src/scenes/experiments/experimentLogic.test.ts',
                'frontend/src/scenes/experiments/README.md',
                'frontend/src/AGENTS.md',
                'frontend/src/design.md',
                'frontend/src/lib/components/owners.yaml',
                'frontend/src/lib/components/ActivityLog/activityLogLogic.test.setup.ts',
                'frontend/src/scenes/data-pipelines/__mocks__/empty.json',
                'frontend/src/scenes/dashboard/dashboardLogic.testHelpers.ts',
                'products/replay_vision/frontend/utils/quotaTestUtils.ts',
                'frontend/src/queries/nodes/HogQLX/__snapshots__/render.test.tsx.snap',
                'frontend/src/lib/api-ratchet-baseline.txt',
                'frontend/bin/layer-baseline.txt',
                'frontend/bin/check-layers.mjs',
                'common/storybook/storybook-timings.json',
                'products/experiments/frontend/generated/api.schemas.ts',
                'products/experiments/frontend/generated/api.zod.ts',
                'products/apm/frontend/generated/api.zod.schemas.ts',
                'frontend/src/generated/core/api.zod.ts',
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
