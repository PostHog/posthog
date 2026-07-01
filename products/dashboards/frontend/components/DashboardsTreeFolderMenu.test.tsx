import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions } from 'kea'

import { LemonDialog } from '@posthog/lemon-ui'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import { DashboardsTreeFolderMenu } from './DashboardsTreeFolderMenu'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn() }))
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonDialog: { openForm: jest.fn() },
}))
// Render each menu item as a plain clickable element so we don't need the Radix DropdownMenu context.
jest.mock('lib/ui/DropdownMenu/DropdownMenu', () => ({
    DropdownMenuItem: ({ children, onClick }: any) => <div onClick={onClick}>{children}</div>,
}))

const folderEntry = (path: string): FileSystemEntry => ({ id: `fs-${path}`, type: 'folder', path }) as FileSystemEntry

describe('DashboardsTreeFolderMenu', () => {
    const createFolder = jest.fn()
    const renameFolder = jest.fn()
    const deleteFolder = jest.fn()
    const openMoveToModal = jest.fn()
    const openForm = LemonDialog.openForm as jest.Mock

    afterEach(cleanup)

    beforeEach(() => {
        ;[createFolder, renameFolder, deleteFolder, openMoveToModal, openForm].forEach((m) => m.mockClear())
        ;(useActions as jest.Mock).mockReturnValue({ createFolder, renameFolder, deleteFolder, openMoveToModal })
    })

    it('shows the full menu for a real folder', () => {
        render(<DashboardsTreeFolderMenu path="Marketing" entry={folderEntry('Marketing')} />)
        expect(screen.getByText('New subfolder')).toBeInTheDocument()
        expect(screen.getByText('Rename')).toBeInTheDocument()
        expect(screen.getByText('Move to...')).toBeInTheDocument()
        expect(screen.getByText('Delete')).toBeInTheDocument()
    })

    it('shows only New folder for the root (no entry)', () => {
        render(<DashboardsTreeFolderMenu path="" />)
        expect(screen.getByText('New folder')).toBeInTheDocument()
        expect(screen.queryByText('Rename')).not.toBeInTheDocument()
        expect(screen.queryByText('Move to...')).not.toBeInTheDocument()
        expect(screen.queryByText('Delete')).not.toBeInTheDocument()
    })

    it('creates a subfolder under the clicked folder', () => {
        render(<DashboardsTreeFolderMenu path="Marketing" entry={folderEntry('Marketing')} />)
        fireEvent.click(screen.getByText('New subfolder'))
        openForm.mock.calls[0][0].onSubmit({ folderName: 'Q1' })
        expect(createFolder).toHaveBeenCalledWith('Q1', 'Marketing')
    })

    it('renames the folder to the submitted name', () => {
        const entry = folderEntry('Marketing/Q1')
        render(<DashboardsTreeFolderMenu path="Marketing/Q1" entry={entry} />)
        fireEvent.click(screen.getByText('Rename'))
        // The rename dialog pre-fills the last path segment.
        expect(openForm.mock.calls[0][0].initialValues).toEqual({ folderName: 'Q1' })
        openForm.mock.calls[0][0].onSubmit({ folderName: 'Q2' })
        expect(renameFolder).toHaveBeenCalledWith(entry, 'Q2')
    })

    it('moves and deletes via the folder entry', () => {
        const entry = folderEntry('Marketing')
        render(<DashboardsTreeFolderMenu path="Marketing" entry={entry} />)
        fireEvent.click(screen.getByText('Move to...'))
        expect(openMoveToModal).toHaveBeenCalledWith([entry])
        fireEvent.click(screen.getByText('Delete'))
        expect(deleteFolder).toHaveBeenCalledWith(entry)
    })
})
