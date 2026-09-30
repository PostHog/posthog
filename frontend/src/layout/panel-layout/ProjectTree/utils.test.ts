import { renderToStaticMarkup } from 'react-dom/server'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import { productsItemName } from '../navbar/tabs/productsCatalog'
import { getCustomIcon } from './customIconRegistry'
import { getDefaultTreeData, getDefaultTreeProducts, iconForType } from './defaultTree'
import {
    convertFileSystemEntryToTreeDataItem,
    escapePath,
    joinPath,
    matchesRefType,
    reparentPath,
    splitPath,
} from './utils'

const catalogProducts = [...getDefaultTreeProducts(), ...getDefaultTreeData()].filter(
    (item) => item.href && item.iconType && !getCustomIcon(item.iconType, item.href)
)

describe('project tree utils', () => {
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
                expect(node.tags).toEqual(item.tags)
                expect(renderToStaticMarkup(node.icon as JSX.Element)).toEqual(
                    renderToStaticMarkup(iconForType(item.iconType, item.iconColor))
                )
            }
        )
    })
})
