import { FileSystemEntry } from '~/queries/schema/schema-general'
import { DashboardBasicType } from '~/types'

import {
    buildEntryByRef,
    buildFolderTree,
    dashboardDraggableId,
    folderBreadcrumb,
    folderContents,
    folderDroppableId,
    folderLabel,
    parseDashboardDragEnd,
} from './dashboardsFileSystemUtils'

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

    it('round-trips a card drag onto a folder header', () => {
        const result = parseDashboardDragEnd(dashboardDraggableId(42), folderDroppableId('Marketing/Q1'))
        expect(result).toEqual({ dashboardId: 42, folder: 'Marketing/Q1' })
    })

    it.each([
        ['no active id', undefined, folderDroppableId('Marketing')],
        ['no over id', dashboardDraggableId(1), undefined],
        ['over is not a folder', dashboardDraggableId(1), 'something-else'],
        ['active is not a dashboard', 'something-else', folderDroppableId('Marketing')],
    ])('returns null when %s', (_description, active, over) => {
        expect(parseDashboardDragEnd(active, over)).toBeNull()
    })

    it('folderContents returns immediate subfolders and direct dashboards at a path', () => {
        const byRef = buildEntryByRef([entry('1', 'Marketing/A'), entry('2', 'Marketing/Q1/B')])
        expect(folderContents([dash(1, 'A'), dash(2, 'B'), dash(3, 'C')], byRef, 'Marketing')).toEqual({
            subfolders: ['Marketing/Q1'],
            dashboards: [dash(1, 'A')],
        })
    })

    it('folderContents at root lists top-level folders only', () => {
        const byRef = buildEntryByRef([entry('1', 'Marketing/A'), entry('2', 'Unfiled/Dashboards/B')])
        expect(folderContents([dash(1, 'A'), dash(2, 'B')], byRef, '')).toEqual({
            subfolders: ['Marketing', 'Unfiled'],
            dashboards: [],
        })
    })

    it('folderBreadcrumb builds root-to-current crumbs', () => {
        expect(folderBreadcrumb('Marketing/Q1')).toEqual([
            { label: 'All dashboards', path: '' },
            { label: 'Marketing', path: 'Marketing' },
            { label: 'Q1', path: 'Marketing/Q1' },
        ])
        expect(folderBreadcrumb('')).toEqual([{ label: 'All dashboards', path: '' }])
    })

    it('folderLabel returns the last path segment', () => {
        expect(folderLabel('Marketing/Q1')).toEqual('Q1')
    })
})
