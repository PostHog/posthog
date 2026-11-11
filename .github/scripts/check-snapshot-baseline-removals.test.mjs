import assert from 'node:assert/strict'
import test from 'node:test'

import {
    findLiveRemovals,
    formatFailure,
    readSnapshotEntries,
    readSnapshottedStories,
} from './check-snapshot-baseline-removals.mjs'

const LONG_KEY_LENGTH = 60

const entryLines = (id) => {
    const comment = id.endsWith('--light') ? ' # approved' : ''
    return id.length > LONG_KEY_LENGTH
        ? [`    ? ${id}${comment}`, `    :   hash: v1.k1.${id.length}.fake`]
        : [`    ${id}:${comment}`, `        hash: v1.k1.${id.length}.fake`]
}

const baselineYaml = (ids) =>
    [
        'version: 1',
        'config:',
        '    api: https://us.example.com',
        "    team: '2'",
        'snapshots: # approved baselines',
        ...ids.flatMap(entryLines),
        '# end of baselines',
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

const LONG_STORY = 'products-dashboards-widget-types-error-tracking-settings--before-ingestion'

const BASE = [
    `${LONG_STORY}--dark`,
    `${LONG_STORY}--light`,
    'settings-form--edited--dark',
    'settings-form--edited--light',
    'settings-form--empty--dark',
    'settings-form--empty--light',
    'widget-grid--default--narrow--dark',
    'widget-grid--default--narrow--light',
]

const STORIES = [
    { id: LONG_STORY, file: 'products/dashboards/frontend/ErrorTrackingSettings.stories.tsx' },
    { id: 'settings-form--edited', file: 'frontend/src/SettingsForm.stories.tsx' },
    { id: 'settings-form--empty', file: 'frontend/src/SettingsForm.stories.tsx' },
    { id: 'widget-grid--default', file: 'products/widgets/frontend/WidgetGrid.stories.tsx' },
]

const cases = [
    {
        name: 'flags every entry of an existing story the PR run does not render',
        head: BASE.filter((id) => !id.startsWith('settings-form--edited')),
        stories: STORIES,
        renderedFiles: [],
        expected: ['settings-form--edited--dark', 'settings-form--edited--light'],
    },
    {
        name: 'flags entries written with explicit keys',
        head: BASE.filter((id) => !id.startsWith(LONG_STORY)),
        stories: STORIES,
        renderedFiles: [],
        expected: [`${LONG_STORY}--dark`, `${LONG_STORY}--light`],
    },
    {
        name: 'passes when the story was deleted or renamed',
        head: BASE.filter((id) => !id.startsWith('widget-grid')),
        stories: STORIES.filter((story) => story.id !== 'widget-grid--default'),
        renderedFiles: [],
        expected: [],
    },
    {
        name: 'passes when the story keeps another variant',
        head: BASE.filter((id) => id !== 'widget-grid--default--narrow--dark'),
        stories: STORIES,
        renderedFiles: [],
        expected: [],
    },
    {
        name: 'passes when the story is tagged test-skip',
        head: BASE.filter((id) => !id.startsWith('widget-grid')),
        stories: STORIES.map((story) =>
            story.id === 'widget-grid--default' ? { ...story, tags: ['dev', 'test', 'test-skip'] } : story
        ),
        renderedFiles: [],
        expected: [],
    },
    {
        name: 'passes when the PR run renders the story',
        head: BASE.filter((id) => !id.startsWith('widget-grid')),
        stories: STORIES,
        renderedFiles: ['products/widgets/frontend/WidgetGrid.stories.tsx'],
        expected: [],
    },
]

for (const { name, head, stories, renderedFiles, expected } of cases) {
    test(name, () => {
        const removals = findLiveRemovals({
            baseIds: new Set(readSnapshotEntries(baselineYaml(BASE)).keys()),
            headIds: new Set(readSnapshotEntries(baselineYaml(head)).keys()),
            stories: readSnapshottedStories(indexJson(stories), 'common/storybook'),
            renderedFiles: new Set(renderedFiles),
        })
        assert.deepEqual(removals, expected)
    })
}

test('the failure prints the removed entries exactly as the base file wrote them', () => {
    const removed = [`${LONG_STORY}--dark`, 'settings-form--edited--dark']
    const message = formatFailure(removed, readSnapshotEntries(baselineYaml(BASE)))
    assert.ok(message.includes(removed.flatMap(entryLines).join('\n')))
})
