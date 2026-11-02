import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { BIField } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biEditorLogic } from './biEditorLogic'
import { BIEditorView, DEFAULT_BI_CONFIG } from './biEditorTypes'
import { biHierarchyLogic } from './biHierarchyLogic'

const levels: BIField[] = ['category', 'subcategory'].map((name) => ({
    id: name,
    name,
    expression: `properties.${name}`,
    type: 'string',
    source: { table: 'events' },
}))
const sourceConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'events' },
    hierarchies: [{ id: 'categories', name: 'Categories', levels }],
}

beforeEach(() => {
    initKeaTests()
    useMocks({
        get: {
            '/api/projects/:team_id/external_data_sources/connections/': [],
            '/api/projects/:team_id/warehouse_saved_queries/': { results: [] },
            '/api/projects/:team_id/insights/910/': {
                id: 910,
                query: { kind: NodeKind.BIVisualizationNode, config: sourceConfig },
            },
            '/api/projects/:team_id/insights/911/': [403, { detail: 'Access denied' }],
        },
        post: { '/api/environments/:team_id/query/': { tables: {} } },
    })
})

it('imports an independent definition without changing the source or the current shelves', async () => {
    const logic = biHierarchyLogic({ tabId: 'hierarchy-test' })
    logic.mount()
    const editor = biEditorLogic({ tabId: 'hierarchy-test' })
    editor.actions.restoreState({
        editorView: BIEditorView.BI,
        config: { ...DEFAULT_BI_CONFIG, source: { table: 'events' }, rows: [levels[0]] },
    })
    await expectLogic(logic, () => logic.actions.loadHierarchySource(910)).toFinishAllListeners()
    expect(logic.values.importHierarchies).toEqual(sourceConfig.hierarchies)
    logic.actions.importHierarchy('categories')
    expect(logic.values.draft?.id).not.toBe('categories')
    expect(logic.values.draft?.levels[0].id).not.toBe('category')
    logic.actions.moveLevel(1, -1)
    logic.actions.saveHierarchy()
    expect(editor.values.config.hierarchies?.[0].levels.map((field) => field.name)).toEqual(['subcategory', 'category'])
    expect(editor.values.config.rows).toEqual([levels[0]])
    expect(logic.values.importHierarchies[0].levels.map((field) => field.name)).toEqual(['category', 'subcategory'])
    logic.unmount()
})

it('clears a previously loaded definition when the next worksheet cannot be accessed', async () => {
    const logic = biHierarchyLogic({ tabId: 'hierarchy-test' })
    logic.mount()
    await expectLogic(logic, () => logic.actions.loadHierarchySource(910)).toFinishAllListeners()
    expect(logic.values.importHierarchies).toHaveLength(1)
    await expectLogic(logic, () => logic.actions.loadHierarchySource(911)).toFinishAllListeners()
    expect(logic.values.importHierarchies).toEqual([])
    expect(logic.values.importError).toBeTruthy()
    expect(logic.values.hierarchySourceLoading).toBe(false)
    logic.unmount()
})
