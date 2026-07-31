import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { buildMarkdownNotebookContent, getMarkdownNotebookMarkdown } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { NotebookNodeType, NotebookTarget, NotebookType } from 'scenes/notebooks/types'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { notebooksModel } from './notebooksModel'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

jest.mock('lib/utils/deleteWithUndo', () => ({
    deleteWithUndo: jest.fn(),
}))

describe('notebooksModel', () => {
    let logic: ReturnType<typeof notebooksModel.build>

    beforeEach(() => {
        initKeaTests()
        logic = notebooksModel()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('creates markdown notebooks with the title and passed content embedded', async () => {
        const createNotebookSpy = mockCreateNotebook()

        await expectLogic(logic, () => {
            logic.actions.createNotebook(NotebookTarget.Scene, 'Activation', [
                {
                    type: NotebookNodeType.Query,
                    attrs: {
                        title: 'Signup',
                        query: { kind: NodeKind.HogQLQuery, query: 'select 1' },
                    },
                },
            ])
        }).toDispatchActions(['createNotebookSuccess'])

        const content = createNotebookSpy.mock.calls[0][0]?.content
        expect(content).toEqual(buildMarkdownNotebookContent(getMarkdownNotebookMarkdown(content)))
        expect(getMarkdownNotebookMarkdown(content)).toContain('# Activation')
        expect(getMarkdownNotebookMarkdown(content)).toContain('<Query')
        expect(getMarkdownNotebookMarkdown(content)).toContain('"kind":"HogQLQuery"')
    })

    it('dispatches notebookRestored when a delete is undone, so the list reloads', async () => {
        const deleteWithUndoMock = jest.mocked(deleteWithUndo)
        deleteWithUndoMock.mockResolvedValue(undefined)

        await expectLogic(logic, () => {
            logic.actions.deleteNotebook('nb1', 'My notebook')
        }).toDispatchActions(['deleteNotebookSuccess'])

        const { callback } = deleteWithUndoMock.mock.calls[0][0]

        await expectLogic(logic, () => {
            callback?.(true, { name: 'My notebook', id: 'nb1' })
        }).toDispatchActions(['notebookRestored'])
    })
})

function mockCreateNotebook(): jest.SpyInstance<
    ReturnType<typeof api.notebooks.create>,
    Parameters<typeof api.notebooks.create>
> {
    return jest.spyOn(api.notebooks, 'create').mockImplementation(async (data) => {
        const notebook: NotebookType = {
            id: 'created-notebook',
            short_id: 'created-notebook',
            created_at: '2026-06-29T00:00:00Z',
            created_by: null,
            version: 1,
            content: data?.content ?? null,
            title: data?.title,
            user_access_level: AccessControlLevel.Editor,
        }

        return notebook
    })
}
