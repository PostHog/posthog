import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { resetAnalyticsFeedSnapshot } from './analyticsFeedLogic'
import { analyticsListLogic } from './analyticsListLogic'
import { analyticsSelectionLogic } from './analyticsSelectionLogic'

const entry = (type: string, ref: string, path: string): Record<string, unknown> => ({
    id: `fs-${ref}`,
    type,
    ref,
    path,
    href: `/x/${ref}`,
    created_at: '2026-09-01T00:00:00Z',
    meta: {},
})

describe('analyticsSelectionLogic', () => {
    let tagRequests: Record<string, unknown>[]

    beforeEach(() => {
        tagRequests = []
        resetAnalyticsFeedSnapshot()
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
                '/api/projects/:team_id/file_system/': {
                    results: [
                        entry('dashboard', '7', 'Growth/Board'),
                        entry('insight/trends', 'abc123', 'Growth/Weekly'),
                        entry('notebook', 'n1', 'Growth/Notes'),
                    ],
                    users: [],
                    next: null,
                },
                '/api/projects/:team_id/insights/': ({ request }) => ({
                    results: new URL(request.url).searchParams.get('short_id') === 'abc123' ? [{ id: 42 }] : [],
                    next: null,
                }),
            },
            post: {
                '/api/projects/:team_id/dashboards/bulk_update_tags/': async ({ request }) => {
                    const body = (await request.json()) as { ids: number[] }
                    tagRequests.push({ type: 'dashboard', ...body })
                    return { updated: body.ids.map((id) => ({ id, tags: [] })), skipped: [] }
                },
                '/api/projects/:team_id/insights/bulk_update_tags/': async ({ request }) => {
                    const body = (await request.json()) as { ids: number[] }
                    tagRequests.push({ type: 'insight', ...body })
                    return { updated: body.ids.map((id) => ({ id, tags: [] })), skipped: [] }
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
        })
    })

    // The list knows an insight by its short id, and the endpoints take numeric ids, so a mix-up tags nothing.
    it('tags the picked dashboards and insights by their numeric ids and leaves the other types out', async () => {
        const list = analyticsListLogic()
        list.mount()
        const logic = analyticsSelectionLogic()
        logic.mount()
        router.actions.push(urls.analyticsList({ folder: 'Growth' }))
        await expectLogic(list).toDispatchActions(['loadFolderContentsSuccess'])
        logic.actions.setRowSelection({ 'dashboard:7': true, 'insight:abc123': true, 'notebook:n1': true })
        expect(logic.values.taggableSelectedItems.map((item) => item.id)).toEqual(['7', 'abc123'])

        logic.actions.openBulkTags('add')
        await expectLogic(logic, () => logic.actions.applyBulkTags(['q4']))
            .toDispatchActions(['bulkTagsDone', 'clearSelection'])
            .toMatchValues({ bulkTagsAction: null, rowSelection: {} })

        expect(tagRequests).toEqual(
            expect.arrayContaining([
                { type: 'dashboard', ids: [7], action: 'add', tags: ['q4'] },
                { type: 'insight', ids: [42], action: 'add', tags: ['q4'] },
            ])
        )
        expect(tagRequests).toHaveLength(2)
    })
})
