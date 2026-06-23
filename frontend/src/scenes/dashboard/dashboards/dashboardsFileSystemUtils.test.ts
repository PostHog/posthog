import { FileSystemEntry } from '~/queries/schema/schema-general'
import { DashboardBasicType } from '~/types'

import { buildEntryByRef, buildFolderTree, folderChildren, subtreeDashboards } from './dashboardsFileSystemUtils'

const dash = (id: number, name: string): DashboardBasicType => ({ id, name }) as DashboardBasicType
const entry = (ref: string, path: string): FileSystemEntry =>
    ({ id: `fs-${ref}`, type: 'dashboard', ref, path }) as FileSystemEntry

describe('dashboardsFileSystemUtils', () => {
    it('indexes only dashboard entries by ref', () => {
        const byRef = buildEntryByRef([
            entry('1', 'Marketing/A'),
            { id: 'fld', type: 'folder', path: 'Marketing' } as FileSystemEntry,
        ])
        expect(Object.keys(byRef)).toEqual(['1'])
    })

    it('builds a nested folder tree from dashboard paths, with ancestors and Unfiled, sorted', () => {
        const dashboards = [dash(1, 'A'), dash(2, 'B'), dash(3, 'C')]
        const byRef = buildEntryByRef([entry('1', 'Marketing/A'), entry('2', 'Marketing/Q1/B')])
        expect(buildFolderTree(dashboards, byRef)).toEqual([
            { path: 'Marketing', label: 'Marketing', children: [{ path: 'Marketing/Q1', label: 'Q1', children: [] }] },
            {
                path: 'Unfiled',
                label: 'Unfiled',
                children: [{ path: 'Unfiled/Dashboards', label: 'Dashboards', children: [] }],
            },
        ])
    })

    it('returns an empty tree when there are no dashboards', () => {
        expect(buildFolderTree([], {})).toEqual([])
    })

    it('buildFolderTree includes empty folder rows (no dashboards beneath) and their ancestors', () => {
        const byRef = buildEntryByRef([entry('1', 'Marketing/A')])
        const tree = buildFolderTree([dash(1, 'A')], byRef, ['Ideas', 'Archive/2024'])
        expect(tree.map((node) => node.path)).toEqual(['Archive', 'Ideas', 'Marketing'])
        expect(tree.find((node) => node.path === 'Archive')?.children.map((c) => c.path)).toEqual(['Archive/2024'])
    })

    it('subtreeDashboards returns every dashboard at or below a folder (root = all)', () => {
        const byRef = buildEntryByRef([
            entry('1', 'Marketing/A'),
            entry('2', 'Marketing/Q1/B'),
            entry('3', 'Product/C'),
        ])
        const dashboards = [dash(1, 'A'), dash(2, 'B'), dash(3, 'C')]
        expect(subtreeDashboards(dashboards, byRef, 'Marketing')).toEqual([dash(1, 'A'), dash(2, 'B')])
        expect(subtreeDashboards(dashboards, byRef, '').map((d) => d.id)).toEqual([1, 2, 3])
    })

    it('folderChildren returns the immediate child folders of a path (root = top level)', () => {
        const tree = buildFolderTree([], {}, ['Marketing/Q1', 'Marketing/Q2', 'Product'])
        expect(folderChildren(tree, '').map((node) => node.path)).toEqual(['Marketing', 'Product'])
        expect(folderChildren(tree, 'Marketing').map((node) => node.path)).toEqual(['Marketing/Q1', 'Marketing/Q2'])
        // A leaf folder has no children; an unknown path returns [].
        expect(folderChildren(tree, 'Product')).toEqual([])
        expect(folderChildren(tree, 'Nope')).toEqual([])
    })

    it('subtreeDashboards treats dashboards with no folder entry as Unfiled', () => {
        const byRef = buildEntryByRef([entry('1', 'Marketing/A')])
        const dashboards = [dash(1, 'A'), dash(2, 'B')]
        // id 2 has no entry → Unfiled/Dashboards; only matches the Unfiled subtree, not Marketing.
        expect(subtreeDashboards(dashboards, byRef, 'Marketing').map((d) => d.id)).toEqual([1])
        expect(subtreeDashboards(dashboards, byRef, 'Unfiled').map((d) => d.id)).toEqual([2])
    })
})
