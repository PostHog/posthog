import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { SchemaItemAction, SchemaItemActionDeps, getSchemaItemActions } from './schemaItemActions'

const makeDeps = (overrides: Partial<SchemaItemActionDeps> = {}): SchemaItemActionDeps => ({
    isEmbeddedMode: false,
    isManagedTrino: false,
    warehouseAccessControlEnabled: false,
    renameSavedViewEnabled: false,
    schemaQueryScope: {},
    joinsByFieldName: {},
    expressionsByFieldName: {},
    previewItem: jest.fn(),
    openPropertyDefinitionEditor: jest.fn(),
    toggleEditJoinModal: jest.fn(),
    deleteJoin: jest.fn(),
    openEditExpressionModal: jest.fn(),
    deleteExpression: jest.fn(),
    openNewExpressionModal: jest.fn(),
    setEditingDraft: jest.fn(),
    deleteDraft: jest.fn(),
    selectSourceTable: jest.fn(),
    openAccessControlModal: jest.fn(),
    openMaterializationModal: jest.fn(),
    openRenameView: jest.fn(),
    createDataWarehouseSavedQueryFolder: jest.fn(),
    updateDataWarehouseSavedQueryFolder: jest.fn(),
    deleteDataWarehouseSavedQueryFolder: jest.fn(),
    deleteDataWarehouseSavedQuery: jest.fn(),
    openUnsavedQuery: jest.fn(),
    deleteUnsavedQuery: jest.fn(),
    ...overrides,
})

// A readable projection of the menu: one string per row, groups as nested arrays, submenus inline.
const describeAction = (action: SchemaItemAction): string | [string, string[]] => {
    const attr = action.dataAttr ? ` [${action.dataAttr}]` : ''
    switch (action.kind) {
        case 'item':
            return `${action.label}${action.destructive ? ' (destructive)' : ''}${attr}`
        case 'link':
            return `${action.label} -> ${action.href}${action.newTab ? ' (new tab)' : ''}${attr}`
        case 'open':
            return `${action.label} -> ${action.href}${action.openInPlace ? '' : ' (new tab)'}`
        case 'submenu':
            return [action.label, action.items.map((sub) => describeAction(sub) as string)]
    }
}

const describeMenu = (item: TreeDataItem, deps: SchemaItemActionDeps): unknown =>
    getSchemaItemActions(item, deps)?.map((group) => group.map(describeAction)) ?? null

describe('getSchemaItemActions', () => {
    test.each<[string, TreeDataItem, Partial<SchemaItemActionDeps>, unknown]>([
        [
            'a warehouse table with access control on',
            {
                id: 't',
                name: 'stripe_charges',
                record: { type: 'table', table: { id: 'tbl-1', name: 'stripe_charges', type: 'data_warehouse' } },
            },
            { warehouseAccessControlEnabled: true },
            [
                [
                    'Query',
                    'See lineage -> /models/tbl-1/lineage?lookup=warehouse_table [sql-editor-sidebar-see-lineage]',
                    'Add join',
                    'Add expression',
                    'Copy table name',
                    'Access control',
                ],
            ],
        ],
        [
            'a table on managed Trino has no lineage, joins, expressions or access control',
            {
                id: 't',
                name: 'orders',
                record: { type: 'table', table: { id: 'tbl-2', name: 'orders', type: 'data_warehouse' } },
            },
            { isManagedTrino: true, warehouseAccessControlEnabled: true },
            [['Query', 'Copy table name']],
        ],
        [
            'a saved view, with delete in its own trailing group',
            {
                id: 'v',
                name: 'revenue',
                record: {
                    type: 'view',
                    isSavedQuery: true,
                    view: { id: 'view-1', name: 'revenue', managed_viewset_kind: null, user_access_level: 'editor' },
                },
            },
            { renameSavedViewEnabled: true, warehouseAccessControlEnabled: true },
            [
                [
                    'Edit view -> /sql?open_view=view-1',
                    'Query',
                    'Rename view [data-warehouse-view-rename]',
                    'See lineage -> /models/view-1/lineage?lookup=saved_query [sql-editor-sidebar-see-lineage]',
                    'Add join',
                    'Materialization',
                    'Copy view name',
                    'Access control',
                ],
                ['Delete view (destructive)'],
            ],
        ],
        [
            'a saved view in the embedded editor opens its editor in a new tab and drops rename and lineage',
            {
                id: 'v',
                name: 'revenue',
                record: {
                    type: 'view',
                    isSavedQuery: true,
                    view: { id: 'view-1', name: 'revenue', managed_viewset_kind: null, user_access_level: 'editor' },
                },
            },
            { isEmbeddedMode: true, renameSavedViewEnabled: true },
            [
                [
                    'Edit view -> /sql?open_view=view-1 (new tab)',
                    'Query',
                    'Add join',
                    'Materialization',
                    'Copy view name',
                ],
                ['Delete view (destructive)'],
            ],
        ],
        [
            'a view folder',
            { id: 'f', name: 'Finance', record: { type: 'folder', folderType: 'view-folder', folder: { id: 'f-1' } } },
            {},
            [['Rename folder'], ['Delete folder (destructive)']],
        ],
        [
            'a source folder with several sources offers a submenu per source',
            {
                id: 's',
                name: 'Stripe',
                record: {
                    type: 'source-folder',
                    sourceType: 'Stripe',
                    sources: [
                        { id: 'src-1', label: 'Stripe EU' },
                        { id: 'src-2', label: 'Stripe US' },
                    ],
                },
            },
            { warehouseAccessControlEnabled: true },
            [
                [
                    [
                        'Edit source',
                        [
                            'Stripe EU -> /data-management/sources/managed-src-1/configuration (new tab)',
                            'Stripe US -> /data-management/sources/managed-src-2/configuration (new tab)',
                        ],
                    ],
                    ['Access control', ['Stripe EU', 'Stripe US']],
                    'Add new source of this type -> /data-warehouse/new-source?kind=Stripe (new tab)',
                ],
            ],
        ],
        [
            'a draft',
            { id: 'd', name: 'My draft', record: { type: 'draft', draft: { id: 'draft-1' } } },
            {},
            [['Rename'], ['Delete (destructive)']],
        ],
        ['the sources header has no menu', { id: 'h', name: 'Sources', record: { type: 'sources' } }, {}, null],
    ])('%s', (_name, item, deps, expected) => {
        expect(describeMenu(item, makeDeps(deps))).toEqual(expected)
    })

    test('a view the user cannot edit disables rename and delete, and their actions do nothing', () => {
        const deps = makeDeps({ renameSavedViewEnabled: true })
        const groups = getSchemaItemActions(
            {
                id: 'v',
                name: 'revenue',
                record: {
                    type: 'view',
                    isSavedQuery: true,
                    view: { id: 'view-1', name: 'revenue', managed_viewset_kind: null, user_access_level: 'viewer' },
                },
            },
            deps
        )
        const rows = groups!.flat()
        const rename = rows.find((row) => row.key === 'rename-view')
        const remove = rows.find((row) => row.key === 'delete-view')

        expect(rename).toMatchObject({ kind: 'item', disabledReason: expect.stringContaining('Requires Editor') })
        expect(remove).toMatchObject({ kind: 'item', disabledReason: expect.stringContaining('Requires Editor') })
        if (rename?.kind === 'item') {
            rename.onSelect()
        }
        expect(deps.openRenameView).not.toHaveBeenCalled()
    })
})
