import type { MouseEvent } from 'react'

import type { LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import type { SavedTicketView } from '../../types'
import {
    FAVORITES_NODE_ID,
    ancestorFolderNodeIds,
    buildTicketViewTree,
    folderNodeId,
    folderPathFromNodeId,
    ticketViewFolderPaths,
    ticketViewMenuItems,
    viewNodeId,
} from './ticketViewFolders'

describe('ticketViewFolders', () => {
    const makeView = (name: string, folder: string, overrides: Partial<SavedTicketView> = {}): SavedTicketView => ({
        id: `id-${name}`,
        short_id: `short-${name}`,
        name,
        filters: {},
        folder,
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        is_favorited: false,
        ...overrides,
    })

    const names = (items: TreeDataItem[]): string[] => items.map((item) => item.name)

    const submenuOf = (item: LemonMenuItem): LemonMenuItem[] => {
        if (!('items' in item) || !item.items) {
            throw new Error(`expected a submenu, got ${JSON.stringify(item)}`)
        }
        return item.items.filter(Boolean) as LemonMenuItem[]
    }
    const clickItem = (item: LemonMenuItem): void => {
        if (!('onClick' in item) || !item.onClick) {
            throw new Error(`expected a clickable item, got ${JSON.stringify(item)}`)
        }
        item.onClick({} as MouseEvent)
    }
    const childOf = (items: TreeDataItem[], name: string): TreeDataItem => {
        const found = items.find((item) => item.name === name)
        if (!found) {
            throw new Error(`no node named ${name} in ${JSON.stringify(names(items))}`)
        }
        return found
    }

    it('nests a folder under its parent', () => {
        const tree = buildTicketViewTree([makeView('Parent', 'Escalations'), makeView('Child', 'Escalations/EU')])

        expect(names(tree)).toEqual(['Escalations'])
        const escalations = childOf(tree, 'Escalations')
        expect(escalations.id).toEqual(folderNodeId('Escalations'))
        expect(names(escalations.children ?? [])).toEqual(['EU', 'Parent'])
        expect(names(childOf(escalations.children ?? [], 'EU').children ?? [])).toEqual(['Child'])
    })

    it('puts a view with no folder at the root, after the folders', () => {
        const tree = buildTicketViewTree([makeView('Loose', ''), makeView('Filed', 'Escalations')])

        expect(names(tree)).toEqual(['Escalations', 'Loose'])
    })

    it('sorts folders before views, each alphabetically', () => {
        const tree = buildTicketViewTree([
            makeView('zeta', ''),
            makeView('alpha', ''),
            makeView('inZ', 'zFolder'),
            makeView('inA', 'aFolder'),
        ])

        expect(names(tree)).toEqual(['aFolder', 'zFolder', 'alpha', 'zeta'])
    })

    it('keeps a folder and a view of the same name apart', () => {
        // Both rows are called "Escalations"; unprefixed ids would collide and make expanding
        // the folder toggle the view.
        const tree = buildTicketViewTree([makeView('Escalations', ''), makeView('Nested', 'Escalations')])

        const ids = tree.map((item) => item.id)
        expect(new Set(ids).size).toEqual(2)
        expect(ids).toContain(folderNodeId('Escalations'))
        expect(ids).toContain(viewNodeId('short-Escalations'))
    })

    it('treats an escaped separator as one folder', () => {
        const tree = buildTicketViewTree([makeView('View', 'Escalations\\/EU')])

        expect(names(tree)).toEqual(['Escalations/EU'])
        expect(tree[0].children).toHaveLength(1)
    })

    it('keeps only matching views and the folders on their paths', () => {
        const views = [
            makeView('Wanted', 'Escalations/EU'),
            makeView('Unwanted', 'Escalations/US'),
            makeView('Elsewhere', 'Billing'),
        ]

        const tree = buildTicketViewTree(views, { matches: [views[0]] })

        expect(names(tree)).toEqual(['Escalations'])
        expect(names(childOf(tree, 'Escalations').children ?? [])).toEqual(['EU'])
    })

    it('gives a favorited view a different id in Favorites than in its folder', () => {
        const tree = buildTicketViewTree([makeView('Starred', 'Escalations', { is_favorited: true })], {
            includeFavorites: true,
        })

        expect(tree[0].id).toEqual(FAVORITES_NODE_ID)
        const favoriteRow = tree[0].children?.[0]
        const folderRow = childOf(tree, 'Escalations').children?.[0]
        expect(favoriteRow?.name).toEqual('Starred')
        expect(folderRow?.name).toEqual('Starred')
        expect(favoriteRow?.id).not.toEqual(folderRow?.id)
    })

    it('omits the Favorites node when nothing is favorited', () => {
        const tree = buildTicketViewTree([makeView('Plain', '')], { includeFavorites: true })

        expect(tree.map((item) => item.id)).not.toContain(FAVORITES_NODE_ID)
    })

    it('collects every folder and ancestor for a picker', () => {
        const paths = ticketViewFolderPaths([makeView('Deep', 'Escalations/EU/Tier1'), makeView('Other', 'Billing')])

        expect(paths).toEqual(['Billing', 'Escalations', 'Escalations/EU', 'Escalations/EU/Tier1'])
    })

    it('returns the whole ancestor chain for a folder', () => {
        expect(ancestorFolderNodeIds('a/b/c')).toEqual([folderNodeId('a'), folderNodeId('a/b'), folderNodeId('a/b/c')])
    })

    it.each([
        ['folder id', folderNodeId('Escalations/EU'), 'Escalations/EU'],
        ['root folder id', folderNodeId(''), ''],
        ['view id', viewNodeId('abc'), null],
        ['favorites node', FAVORITES_NODE_ID, null],
    ])('reads the folder path back from a %s', (_label, id, expected) => {
        expect(folderPathFromNodeId(id as string)).toEqual(expected)
    })

    it('collapses folders past the depth cap into a browse row', () => {
        const tree = buildTicketViewTree([makeView('Deep', 'a/b/c')])
        const onBrowseFolder = jest.fn()

        const items = ticketViewMenuItems(tree, { onSelectView: jest.fn(), onBrowseFolder })

        // Depth 1 "a" nests; depth 2 "b" is the cap, so it offers to browse instead of nesting deeper
        const browse = submenuOf(items[0])[0]
        expect(browse.label).toEqual('Browse "b" (1)')
        expect('items' in browse && browse.items).toBeFalsy()
        clickItem(browse)
        expect(onBrowseFolder).toHaveBeenCalledWith('a/b')
    })

    it('selects a view from a menu leaf', () => {
        const view = makeView('Loose', '')
        const onSelectView = jest.fn()

        const items = ticketViewMenuItems(buildTicketViewTree([view]), { onSelectView, onBrowseFolder: jest.fn() })
        clickItem(items[0])

        expect(onSelectView).toHaveBeenCalledWith(view)
    })
})
