import assert from 'node:assert/strict'
import test from 'node:test'

import { findLiveRemovals, readSnapshotIds, readSnapshottedStories } from './check-snapshot-baseline-removals.mjs'

const baselineYaml = (ids) =>
    [
        'version: 1',
        'config:',
        '    api: https://us.example.com',
        "    team: '2'",
        'snapshots:',
        ...ids.flatMap((id) => [`    ${id}:`, `        hash: v1.k1.${id.length}.fake`]),
        '',
    ].join('\n')

const indexJson = (stories) =>
    JSON.stringify({
        v: 5,
        entries: Object.fromEntries([
            [
                'settings-form--docs',
                { type: 'docs', id: 'settings-form--docs', importPath: '../../frontend/src/SettingsForm.mdx' },
            ],
            ...stories.map(({ id, file, tags = ['dev', 'test'] }) => [
                id,
                { type: 'story', id, importPath: `../../${file}`, tags },
            ]),
        ]),
    })

const BASE = [
    'settings-form--edited--dark',
    'settings-form--edited--light',
    'settings-form--empty--dark',
    'settings-form--empty--light',
    'widget-grid--default--narrow--dark',
    'widget-grid--default--narrow--light',
]

const STORIES = [
    { id: 'settings-form--edited', file: 'frontend/src/SettingsForm.stories.tsx' },
    { id: 'settings-form--empty', file: 'frontend/src/SettingsForm.stories.tsx' },
    { id: 'widget-grid--default', file: 'products/widgets/frontend/WidgetGrid.stories.tsx' },
]

const cases = [
    {
        name: 'flags every entry of an untouched story that still exists',
        head: BASE.filter((id) => !id.startsWith('settings-form--edited')),
        stories: STORIES,
        changedFiles: ['frontend/snapshots.yml'],
        expected: ['settings-form--edited--dark', 'settings-form--edited--light'],
    },
    {
        name: 'passes when the story was deleted or renamed',
        head: BASE.filter((id) => !id.startsWith('widget-grid')),
        stories: STORIES.filter((story) => story.id !== 'widget-grid--default'),
        changedFiles: ['frontend/snapshots.yml'],
        expected: [],
    },
    {
        name: 'passes when the story keeps another variant',
        head: BASE.filter((id) => id !== 'widget-grid--default--narrow--dark'),
        stories: STORIES,
        changedFiles: ['frontend/snapshots.yml'],
        expected: [],
    },
    {
        name: 'passes when the story is tagged test-skip',
        head: BASE.filter((id) => !id.startsWith('widget-grid')),
        stories: STORIES.map((story) =>
            story.id === 'widget-grid--default' ? { ...story, tags: ['dev', 'test', 'test-skip'] } : story
        ),
        changedFiles: ['frontend/snapshots.yml'],
        expected: [],
    },
    {
        name: 'passes when the PR changes the story file, so its own run renders the story',
        head: BASE.filter((id) => !id.startsWith('widget-grid')),
        stories: STORIES,
        changedFiles: ['frontend/snapshots.yml', 'products/widgets/frontend/WidgetGrid.stories.tsx'],
        expected: [],
    },
]

for (const { name, head, stories, changedFiles, expected } of cases) {
    test(name, () => {
        const removals = findLiveRemovals({
            baseIds: readSnapshotIds(baselineYaml(BASE)),
            headIds: readSnapshotIds(baselineYaml(head)),
            stories: readSnapshottedStories(indexJson(stories), 'common/storybook'),
            changedFiles: new Set(changedFiles),
        })
        assert.deepEqual(removals, expected)
    })
}
