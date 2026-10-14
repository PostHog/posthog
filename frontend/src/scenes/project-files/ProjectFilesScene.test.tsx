import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { ProjectFilesScene } from './ProjectFilesScene'

jest.mock('~/layout/panel-layout/ProjectTree/ProjectTree', () => ({
    ProjectTree: ({ root }: { root: string }) => <div>{root}</div>,
}))

describe('project files scene', () => {
    it('opens the URL folder and follows query changes without remounting', async () => {
        initKeaTests()
        router.actions.push(urls.projectFiles('Research & notes/Reports'))
        render(<ProjectFilesScene />)
        expect(screen.getByText('Research & notes/Reports')).toBeInTheDocument()
        expect(screen.getByText('project://Research & notes/Reports')).toBeInTheDocument()
        expect(screen.getByLabelText('Parent folder')).toHaveAttribute(
            'href',
            expect.stringContaining('folder=Research%20%26%20notes')
        )
        router.actions.push(urls.projectFiles())
        await waitFor(() => expect(screen.getByText('Project')).toBeInTheDocument())
        expect(screen.getByText('project://')).toBeInTheDocument()
        expect(screen.queryByLabelText('Parent folder')).not.toBeInTheDocument()
    })
})
