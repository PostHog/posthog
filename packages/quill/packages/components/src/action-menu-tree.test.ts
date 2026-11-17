import { type ActionMenuItem, collectDestructive, hasRows, searchActionMenu } from './action-menu-tree'

const noop = (): void => {}

const ITEMS: ActionMenuItem[] = [
    {
        type: 'submenu',
        id: 'file',
        label: 'File',
        items: [
            { type: 'submenu', id: 'export', label: 'Export', items: [{ id: 'csv', label: 'CSV', onSelect: noop }] },
            {
                type: 'submenu',
                id: 'notebooks',
                label: 'Add to notebook',
                display: 'submenu',
                searchable: false,
                items: [{ id: 'nb', label: 'Weekly notes', onSelect: noop }],
            },
            { id: 'delete', label: 'Delete insight', destructive: true, onSelect: noop },
        ],
    },
    {
        type: 'submenu',
        id: 'edit',
        label: 'Edit',
        items: [
            {
                type: 'radio',
                id: 'status',
                label: 'Status',
                value: 'active',
                options: [
                    { value: 'active', label: 'Active' },
                    { value: 'resolved', label: 'Resolved' },
                ],
                onValueChange: noop,
            },
            { id: 'restore', label: 'Restore deleted tiles', onSelect: noop },
            {
                type: 'submenu',
                id: 'customize',
                label: 'Customize',
                display: 'submenu',
                items: [{ id: 'reset', label: 'Delete layout', destructive: true, onSelect: noop }],
            },
        ],
    },
    {
        type: 'submenu',
        id: 'danger',
        label: 'Danger',
        items: [{ id: 'archive', label: 'Archive', destructive: true, onSelect: noop }],
    },
]

function describeResults(query: string): string[] {
    return searchActionMenu(ITEMS, query).map((result) =>
        result.kind === 'radio-option'
            ? [...result.path, result.option.label].join(' › ')
            : [...result.path, result.item.label].join(' › ')
    )
}

describe('action menu tree', () => {
    test.each([
        ['reaches into submenus and carries the path', 'csv', ['File › Export › CSV']],
        [
            'matches on the path, so a submenu label finds its rows after the submenu itself',
            'export',
            ['File › Export', 'File › Export › CSV'],
        ],
        ['lists an unsearchable submenu as one row and skips its rows', 'notebook', ['File › Add to notebook']],
        ['never reaches rows inside an unsearchable submenu', 'weekly', []],
        ['lists radio options as rows under the radio label', 'resolved', ['Edit › Status › Resolved']],
        [
            'puts destructive rows last',
            'delete',
            ['Edit › Restore deleted tiles', 'File › Delete insight', 'Edit › Customize › Delete layout'],
        ],
        ['ignores case and accents', 'ÉXPORT csv', ['File › Export › CSV']],
        ['returns nothing for a blank query', '   ', []],
    ])('search %s', (_, query, expected) => {
        expect(describeResults(query)).toEqual(expected)
    })

    test('hoists destructive rows except those inside a kept submenu', () => {
        expect(collectDestructive(ITEMS).map((item) => item.id)).toEqual(['delete', 'archive'])
    })

    test.each([
        ['a menu of only hoisted destructive rows is hidden', 'danger', true, false],
        ['the same menu shows where nothing is hoisted', 'danger', false, true],
        ['a kept submenu keeps its destructive rows', 'edit', true, true],
    ])('%s', (_, id, hoisting, expected) => {
        expect(hasRows(ITEMS.find((item) => item.id === id)!, hoisting)).toBe(expected)
    })
})
