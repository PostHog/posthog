import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'

jest.mock('./migrations/migrate', () => {
    const actual = jest.requireActual('./migrations/migrate')
    return { ...actual, migrate: jest.fn(async (notebook: unknown) => notebook) }
})

const SHORT_ID = 'dep-graph-run-state'

// `a` exports sql_df; `b` reads it, so the loaded notebook has one edge a -> b.
const LOADED_MARKDOWN = [
    '<SQLV2 nodeId="a" returnVariable="sql_df" code="select id from events" />',
    '<SQLV2 nodeId="b" returnVariable="joined" code="select * from sql_df" />',
].join('\n\n')

// The same two cells, but `b` no longer reads sql_df, so a live graph would drop the edge.
const EDITED_MARKDOWN = [
    '<SQLV2 nodeId="a" returnVariable="sql_df" code="select id from events" />',
    '<SQLV2 nodeId="b" returnVariable="joined" code="select 1" />',
].join('\n\n')

const notebookFixture: NotebookType = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Dependency graph run state',
    content: buildMarkdownNotebookContent(LOADED_MARKDOWN),
    text_content: '',
    version: 1,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
    variables: [],
}

describe('notebook dependency graph run state', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let stalenessLogic: ReturnType<typeof notebookNodeStalenessLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, notebookFixture],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/`]: () => [200, notebookFixture],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/kernel/status/`]: () => [200, { backend: null }],
            },
        })
        initKeaTests()
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)
        jest.spyOn(api.notebooks, 'update').mockImplementation(async (_shortId: string, data: Record<string, any>) => ({
            ...notebookFixture,
            ...data,
        }))

        stalenessLogic = notebookNodeStalenessLogic({ shortId: SHORT_ID })
        stalenessLogic.mount()
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook', cachedNotebook: notebookFixture })
        logic.mount()
        logic.actions.loadNotebook()
    })

    afterEach(() => {
        logic?.unmount()
        stalenessLogic?.unmount()
        jest.restoreAllMocks()
    })

    const edgeTargets = (): string[] =>
        logic.values.dependencyGraph.downstreamUsageByNode['a']?.sql_df?.map((usage) => usage.nodeId) ?? []

    it('freezes the dependency graph to run state: seeded on load, held on edit, refreshed on run', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(edgeTargets()).toEqual(['b'])

        // The edit drops b's reference; the edge must hold until a run, or the graph tracks live text.
        logic.actions.setLocalContent(buildMarkdownNotebookContent(EDITED_MARKDOWN))
        await expectLogic(logic).toFinishAllListeners()
        expect(edgeTargets()).toEqual(['b'])

        // A failed run carries no executed document, so it must not advance the snapshot.
        stalenessLogic.actions.nodeRunFinished('b', 'failed', null)
        await expectLogic(logic).toFinishAllListeners()
        expect(edgeTargets()).toEqual(['b'])

        // A successful run reports the executed document, so the snapshot refreshes and the edge drops.
        stalenessLogic.actions.nodeRunFinished('b', 'done', buildMarkdownNotebookContent(EDITED_MARKDOWN))
        await expectLogic(logic).toFinishAllListeners()
        expect(edgeTargets()).toEqual([])
    })
})
