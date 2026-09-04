jest.mock('scenes/data-warehouse/editor/SQLEditor', () => ({
    SQLEditor: () => null,
    SQLEditorPanel: {
        Output: 'output',
    },
}))

jest.mock('scenes/data-warehouse/editor/sqlEditorLogic', () => ({
    sqlEditorLogic: { findMounted: jest.fn(() => null) },
}))

import { act, fireEvent, render } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { type NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { type JSONContent } from 'lib/components/RichContentEditor/types'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { type NotebookLogicProps, notebookLogic } from '../../Notebook/notebookLogic'
import { NotebookNodeType, type NotebookType } from '../../types'
import { NotebookCodeCellRunButton } from './NotebookCodeCellRunButton'

describe('NotebookCodeCellRunButton', () => {
    const SHORT_ID = 'test-run-button'
    const NODE_ID = 'sql-cell-1'
    const DOCUMENT_SQL = 'select 1'

    const LOGIC_PROPS: NotebookLogicProps = { shortId: SHORT_ID, mode: 'notebook' }

    const NODE: NotebookComponentBlockNode = {
        id: 'block-1',
        type: 'component',
        tagName: 'SQLV2',
        props: { nodeId: NODE_ID },
    }

    const CONTENT: JSONContent = {
        type: 'doc',
        content: [
            {
                type: NotebookNodeType.SQLV2,
                attrs: { nodeId: NODE_ID, code: DOCUMENT_SQL, returnVariable: 'sql_df' },
            },
        ],
    }

    const notebookWith = (userAccessLevel: AccessControlLevel): NotebookType =>
        ({
            id: 'notebook-id',
            short_id: SHORT_ID,
            title: 'Run button',
            content: CONTENT,
            text_content: DOCUMENT_SQL,
            version: 1,
            deleted: false,
            is_template: false,
            user_access_level: userAccessLevel,
            created_at: '2025-01-01T00:00:00Z',
            created_by: null,
            last_modified_at: '2025-01-01T00:00:00Z',
            last_modified_by: null,
        }) as unknown as NotebookType

    let logic: ReturnType<typeof notebookLogic.build>
    let runSpy: jest.SpyInstance

    const mountNotebook = async (userAccessLevel: AccessControlLevel): Promise<void> => {
        jest.spyOn(api.notebooks, 'get').mockResolvedValue(notebookWith(userAccessLevel))
        logic = notebookLogic(LOGIC_PROPS)
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
    }

    const renderButton = (): HTMLElement | null => {
        const { container } = render(
            <BindLogic logic={notebookLogic} props={LOGIC_PROPS}>
                <NotebookCodeCellRunButton node={NODE} notebookMode="view" updateProps={jest.fn()} />
            </BindLogic>
        )
        return container.querySelector('[data-attr="notebook-code-cell-run-button"]')
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)
        runSpy = jest.spyOn(api.notebooks, 'sqlV2Run').mockResolvedValue({ run_id: 'r1' })
        jest.spyOn(api.notebooks, 'sqlV2RunResult').mockResolvedValue({ status: 'running', result: null, error: null })
        ;(sqlEditorLogic.findMounted as jest.Mock).mockReturnValue(null)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        ['an editor', AccessControlLevel.Editor, false, true],
        ['a viewer', AccessControlLevel.Viewer, false, false],
        ['an editor previewing an older version', AccessControlLevel.Editor, true, false],
    ] as const)(
        'offers the control to %s',
        async (_label, userAccessLevel, isPreviewing, expectsControl): Promise<void> => {
            await mountNotebook(userAccessLevel)
            if (isPreviewing) {
                logic.actions.setPreviewContent(CONTENT)
            }

            expect(renderButton() !== null).toBe(expectsControl)
        }
    )

    it.each([
        ['an empty editor', '', 0],
        ['an editor holding newer code', 'select 2', 1],
    ] as const)(
        'runs what %s holds rather than the code the document still carries',
        async (_label, queryInput, expectedRuns): Promise<void> => {
            await mountNotebook(AccessControlLevel.Editor)
            ;(sqlEditorLogic.findMounted as jest.Mock).mockReturnValue({
                values: { queryInput, selectedConnectionId: null, sendRawQueryEnabled: false },
            })

            const button = renderButton()
            await act(async () => {
                fireEvent.click(button as HTMLElement)
            })

            expect(runSpy).toHaveBeenCalledTimes(expectedRuns)
            if (expectedRuns > 0) {
                expect(runSpy).toHaveBeenCalledWith(SHORT_ID, expect.objectContaining({ code: queryInput }))
            }
        }
    )
})
