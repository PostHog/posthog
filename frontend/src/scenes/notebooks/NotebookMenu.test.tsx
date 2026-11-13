import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import { type ReactNode } from 'react'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookPrintControls } from 'products/notebooks/frontend/NotebookPrintControls'

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

const legacyNotebook: NotebookType = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Legacy notebook',
    content: {
        type: 'doc',
        content: [{ type: 'paragraph', content: [{ type: 'text', text: 'legacy notebook' }] }],
    },
    text_content: 'legacy notebook',
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

describe('NotebookMenu', () => {
    let logic: ReturnType<typeof notebookLogic.build>

    beforeEach(async () => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api, 'stream').mockResolvedValue(undefined as any)

        logic = notebookLogic({ shortId: SHORT_ID, cachedNotebook: legacyNotebook })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('shows the markdown download action for legacy notebooks rendered as markdown', () => {
        render(<NotebookMenu shortId={SHORT_ID} />)

        expect(screen.getByText('Download .md')).toBeInTheDocument()
        expect(screen.queryByText('Export JSON')).not.toBeInTheDocument()
    })

    test.each(['afterprint', 'unmount'])('restores the page after notebook printing ends with %s', (end) => {
        const originalTitle = document.title
        const print = jest.spyOn(window, 'print').mockImplementation(() => {})
        const { container, unmount } = render(
            <>
                <NotebookMenu shortId={SHORT_ID} />
                <NotebookPrintControls shortId={SHORT_ID} />
                <div className="Notebook" data-notebook-short-id={SHORT_ID} />
                <div className="Notebook" data-notebook-short-id="another-notebook" />
            </>
        )

        fireEvent.click(screen.getByText('Print / save PDF'))
        expect(print).not.toHaveBeenCalled()
        fireEvent.click(screen.getByText('Print'))

        expect(print).toHaveBeenCalledTimes(1)
        expect(container.querySelector('.Notebook--printing')).toHaveAttribute('data-notebook-short-id', SHORT_ID)
        expect(document.querySelectorAll('.Notebook--printing')).toHaveLength(1)
        expect(document.title).toEqual('Legacy notebook')

        if (end === 'afterprint') {
            window.dispatchEvent(new Event('afterprint'))
        } else {
            unmount()
        }

        expect(document.querySelector('.NotebookPrintAncestor')).toBeNull()
        expect(container.querySelector('.Notebook--printing')).toBeNull()
        expect(document.title).toEqual(originalTitle)
    })
})
