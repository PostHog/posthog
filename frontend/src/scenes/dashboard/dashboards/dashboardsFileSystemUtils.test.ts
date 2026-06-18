import { FileSystemEntry } from '~/queries/schema/schema-general'
import { DashboardBasicType } from '~/types'

import {
    buildEntryByRef,
    dashboardDraggableId,
    folderDroppableId,
    groupDashboardsByFolder,
    parseDashboardDragEnd,
    UNFILED_DASHBOARDS_FOLDER,
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

    it('groups dashboards under their folder, defaulting to Unfiled, folders sorted', () => {
        const dashboards = [dash(1, 'A'), dash(2, 'B'), dash(3, 'C')]
        const byRef = buildEntryByRef([entry('1', 'Marketing/A'), entry('2', 'Marketing/B')])
        expect(groupDashboardsByFolder(dashboards, byRef)).toEqual([
            { folder: 'Marketing', dashboards: [dash(1, 'A'), dash(2, 'B')] },
            { folder: UNFILED_DASHBOARDS_FOLDER, dashboards: [dash(3, 'C')] },
        ])
    })

    it('returns an empty array when there are no dashboards', () => {
        expect(groupDashboardsByFolder([], {})).toEqual([])
    })

    it('round-trips a card drag onto a folder header', () => {
        const result = parseDashboardDragEnd(dashboardDraggableId(42), folderDroppableId('Marketing/Q1'))
        expect(result).toEqual({ dashboardId: 42, folder: 'Marketing/Q1' })
    })

    it.each([
        [undefined, folderDroppableId('Marketing'), 'no active id'],
        [dashboardDraggableId(1), undefined, 'no over id'],
        [dashboardDraggableId(1), 'something-else', 'over is not a folder'],
        ['something-else', folderDroppableId('Marketing'), 'active is not a dashboard'],
    ])('returns null for an invalid drop (%s)', (active, over) => {
        expect(parseDashboardDragEnd(active, over)).toBeNull()
    })
})
