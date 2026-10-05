import { renderToStaticMarkup } from 'react-dom/server'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'
import { ProjectTreeRef } from '~/types'

import { productsItemName } from '../navbar/tabs/productsCatalog'
import { getCustomIcon } from './customIconRegistry'
import { getDefaultTreeData, getDefaultTreeProducts, iconForType } from './defaultTree'
import {
    convertFileSystemEntryToTreeDataItem,
    escapePath,
    isProjectTreeItemActive,
    joinPath,
    matchesRefType,
    reparentPath,
    resolveProjectTreeDrop,
    splitPath,
} from './utils'

const catalogProducts = [...getDefaultTreeProducts(), ...getDefaultTreeData()].filter(
    (item) => item.href && item.iconType && !getCustomIcon(item.iconType, item.href)
)

describe('project tree utils', () => {
    describe('isProjectTreeItemActive', () => {
        const insight: TreeDataItem = {
            id: 'project/sql-insight',
            name: 'SQL insight',
            record: { type: 'insight', ref: 'sql123', href: '/insights/sql123' },
        }

        it.each<[string, string, ProjectTreeRef | null, boolean]>([
            ['view mode', '/insights/sql123', null, true],
            ['edit mode', '/sql', { type: 'insight', ref: 'sql123' }, true],
            ['another insight', '/sql', { type: 'insight', ref: 'other' }, false],
            ['another resource with the same ID', '/sql', { type: 'dashboard', ref: 'sql123' }, false],
            ['unsaved SQL', '/sql', null, false],
            ['new insight', '/sql', { type: 'insight', ref: null }, false],
        ])('highlights the current insight in %s', (_, pathname, ref, expected) => {
            expect(isProjectTreeItemActive(insight, pathname, ref)).toBe(expected)
        })
    })

    describe('resolveProjectTreeDrop', () => {
        const note: FileSystemEntry = { id: 'note', type: 'notebook', ref: 'note-ref', path: 'Research/Notes' }
        const folder: FileSystemEntry = { id: 'folder', type: 'folder', path: 'Research' }
        const shortcuts: FileSystemEntry[] = [
            { id: 'home', type: 'folder', path: 'My home', ref: 'Users/Alex' },
            { id: 'overview', type: 'dashboard', path: 'Overview', ref: 'overview-ref' },
        ]

        it.each([
            ['shortcuts://My home', 'Users/Alex'],
            ['project://Research', 'Research'],
            ['project://', ''],
            ['', ''],
        ])('resolves a drop on %s to its real folder', (overId, destination) => {
            expect(resolveProjectTreeDrop('project/note', overId, [note, folder], shortcuts)).toEqual({
                type: 'move',
                item: note,
                folder: destination,
            })
        })

        it.each([
            ['shortcuts://', 'onto'],
            ['shortcuts/overview', 'onto'],
            ['shortcuts://My home', 'before'],
            ['shortcuts://My home', 'after'],
        ] as const)('stars a nested file dropped on %s (%s) without moving it', (overId, position) => {
            expect(resolveProjectTreeDrop('project/note', overId, [note], shortcuts, position)).toEqual({
                type: 'star',
                item: note,
            })
            expect(
                resolveProjectTreeDrop(
                    'project/note',
                    overId,
                    [note],
                    [...shortcuts, { id: 'star-note', type: 'notebook', ref: 'note-ref', path: 'Notes' }],
                    position
                )
            ).toBeNull()
        })

        it.each([null, 'missing', 'shortcuts/missing', 'project/note', 'project://missing'])(
            'does not move a file to the project root for an invalid target %s',
            (overId) => {
                expect(resolveProjectTreeDrop('project/note', overId, [note], shortcuts)).toBeNull()
            }
        )

        it.each(['project/note', 'shortcuts/star-note'])(
            'moves %s into a starred folder without adding a shortcut',
            (activeId) => {
                const starredNote = { id: 'star-note', type: 'notebook', ref: 'note-ref', path: 'Notes' }
                expect(
                    resolveProjectTreeDrop(activeId, 'shortcuts://My home', [note], [...shortcuts, starredNote], 'onto')
                ).toEqual({
                    type: activeId.startsWith('shortcuts/') ? 'move-shortcut' : 'move',
                    item: activeId.startsWith('shortcuts/') ? starredNote : note,
                    folder: 'Users/Alex',
                })
                expect(resolveProjectTreeDrop(activeId, 'shortcuts://', [note], [...shortcuts, starredNote])).toBeNull()
            }
        )

        it('reorders starred folders without moving their contents', () => {
            expect(
                resolveProjectTreeDrop('shortcuts/overview', 'shortcuts://My home', [], shortcuts, 'before')
            ).toEqual({
                type: 'reorder',
                activeId: 'shortcuts/overview',
                overId: 'shortcuts://My home',
            })
            expect(resolveProjectTreeDrop('shortcuts://My home', 'project://Research', [folder], shortcuts)).toEqual({
                type: 'move-shortcut',
                item: shortcuts[0],
                folder: 'Research',
            })
        })
    })

    describe('escapePath', () => {
        it('escapes paths as expected', () => {
            expect(escapePath('a/b')).toEqual('a\\/b')
            expect(escapePath('a/b\\')).toEqual('a\\/b\\\\')
            expect(escapePath('a/b/c')).toEqual('a\\/b\\/c')
            expect(escapePath('a\n\t')).toEqual('a\n\t')
            expect(escapePath('a')).toEqual('a')
            expect(escapePath('')).toEqual('')
        })
    })

    describe('splitPath', () => {
        it('splits paths as expected', () => {
            expect(splitPath('a/b')).toEqual(['a', 'b'])
            expect(splitPath('a\\/b/c')).toEqual(['a/b', 'c'])
            expect(splitPath('a\\/b\\\\/c')).toEqual(['a/b\\', 'c'])
            expect(splitPath('a\\/b\\/c')).toEqual(['a/b/c'])
            expect(splitPath('a\n\t/b')).toEqual(['a\n\t', 'b'])
            expect(splitPath('a\\n\\t/b')).toEqual(['a\\n\\t', 'b'])
            expect(splitPath('a\\\\n\\t/b')).toEqual(['a\\n\\t', 'b'])
            expect(splitPath('a')).toEqual(['a'])
            expect(splitPath('')).toEqual([])
        })
    })

    describe('joinPath', () => {
        it('joins paths as expected', () => {
            expect(joinPath(['a', 'b'])).toEqual('a/b')
            expect(joinPath(['a/b', 'c'])).toEqual('a\\/b/c')
            expect(joinPath(['a/b\\', 'c'])).toEqual('a\\/b\\\\/c')
            expect(joinPath(['a/b/c'])).toEqual('a\\/b\\/c')
            expect(joinPath(['a\n\t', 'b'])).toEqual('a\n\t/b')
            expect(joinPath(['a\\n\\t', 'b'])).toEqual('a\\\\n\\\\t/b')
            expect(joinPath(['a'])).toEqual('a')
            expect(joinPath([])).toEqual('')
        })
    })

    describe('reparentPath', () => {
        it('rewrites the moved folder and everything under it', () => {
            expect(reparentPath('Revenue', 'Revenue', 'Finance/Revenue')).toEqual('Finance/Revenue')
            expect(reparentPath('Revenue/Q3', 'Revenue', 'Finance/Revenue')).toEqual('Finance/Revenue/Q3')
        })

        it('leaves a sibling whose name merely starts the same', () => {
            expect(reparentPath('Revenue archive', 'Revenue', 'Finance/Revenue')).toBeNull()
        })

        it('leaves paths outside the moved folder', () => {
            expect(reparentPath('Marketing/Q3', 'Revenue', 'Finance/Revenue')).toBeNull()
            expect(reparentPath(undefined, 'Revenue', 'Finance')).toBeNull()
        })

        it('treats an escaped separator as part of a name, not a boundary', () => {
            // "Revenue\/Q3" is one folder literally named "Revenue/Q3", not Q3 inside Revenue.
            expect(reparentPath('Revenue\\/Q3', 'Revenue', 'Finance')).toBeNull()
        })

        it('moves a folder to the project root', () => {
            expect(reparentPath('Revenue/Q3', 'Revenue', 'Revenue2')).toEqual('Revenue2/Q3')
        })
    })

    describe('matchesRefType', () => {
        it('matches an exact type', () => {
            expect(matchesRefType('dashboard', 'dashboard')).toBe(true)
            expect(matchesRefType('insight', 'dashboard')).toBe(false)
        })

        it('treats a trailing slash as a prefix over internal types', () => {
            expect(matchesRefType('hog/site_destination', 'hog/')).toBe(true)
            expect(matchesRefType('hog/transformation', 'hog/')).toBe(true)
            expect(matchesRefType('dashboard', 'hog/')).toBe(false)
        })

        it('does not match a row with no type', () => {
            expect(matchesRefType(undefined, 'hog/')).toBe(false)
            expect(matchesRefType(undefined, 'dashboard')).toBe(false)
        })
    })

    it.each(['trends', 'funnels', 'retention', 'paths', 'lifecycle', 'stickiness', 'hog', undefined, 'unknown'])(
        'renders a saved insight with type %s using its insight icon',
        (insightType) => {
            const [node] = convertFileSystemEntryToTreeDataItem({
                imports: [{ id: 'report', path: 'Report', type: 'insight', meta: { insight_type: insightType } }],
                folderStates: {},
                checkedItems: {},
                root: 'project://',
            })
            const expectedType = insightType && insightType !== 'unknown' ? `insight/${insightType}` : 'insight'
            expect(renderToStaticMarkup(node.icon as JSX.Element)).toEqual(
                renderToStaticMarkup(iconForType(expectedType as FileSystemIconType))
            )
        }
    )

    describe('starred products', () => {
        it.each(catalogProducts.map((item) => [item.path, item]))(
            'renders a starred %s with the name, tags, icon and color it has in the product list',
            (_path, item) => {
                // A star saved before a rename or an icon change still carries the older name and type, and no tags.
                const shortcut = {
                    id: 'star',
                    path: 'Old product name',
                    type: 'folder_open',
                    href: item.href,
                } as FileSystemEntry
                const [node] = convertFileSystemEntryToTreeDataItem({
                    imports: [shortcut],
                    folderStates: {},
                    checkedItems: {},
                    root: 'shortcuts://',
                    disableCategories: true,
                })
                expect(node.name).toEqual(productsItemName(item))
                expect(renderToStaticMarkup(node.icon as JSX.Element)).toEqual(
                    renderToStaticMarkup(iconForType(item.iconType, item.iconColor))
                )
            }
        )
    })
})
