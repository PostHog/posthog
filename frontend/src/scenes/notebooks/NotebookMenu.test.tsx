import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import { type ReactNode } from 'react'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { buildMarkdownNotebookContent } from './Notebook/markdownNotebookV2'
import { notebookLogic } from './Notebook/notebookLogic'
import { NotebookMenu } from './NotebookMenu'
import { type NotebookType } from './types'

jest.mock('./Notebook/migrations/migrate', () => {
    const actual = jest.requireActual('./Notebook/migrations/migrate')
    return {
        ...actual,
        migrate: jest.fn(async (notebook) => notebook),
    }
})

jest.mock('lib/ui/DropdownMenu/DropdownMenu', () => ({
    DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

const SHORT_ID = 'test-notebook-menu'

const markdownNotebook: NotebookType = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Markdown notebook',
    content: buildMarkdownNotebookContent('# Markdown notebook'),
    text_content: '# Markdown notebook',
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

const legacyPreviewContent = {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'legacy preview' }] }],
}

describe('NotebookMenu', () => {
    let logic: ReturnType<typeof notebookLogic.build>

    beforeEach(async () => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)

        logic = notebookLogic({ shortId: SHORT_ID, cachedNotebook: markdownNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('shows the markdown download action for markdown notebooks even while previewing legacy content', () => {
        logic.actions.setPreviewContent(legacyPreviewContent)

        render(<NotebookMenu shortId={SHORT_ID} />)

        expect(screen.getByText('Download .md')).toBeInTheDocument()
        expect(screen.queryByText('Export JSON')).not.toBeInTheDocument()
    })
})
