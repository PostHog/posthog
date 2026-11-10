import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import * as retryImportUtils from 'lib/utils/retryImport'
import { buildMarkdownNotebookContent, getMarkdownNotebookMarkdown } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { NotebookNodeType, NotebookTarget, NotebookType } from 'scenes/notebooks/types'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { SCRATCHPAD_NOTEBOOK, notebooksModel } from './notebooksModel'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
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

    it.each([false, true])('creates markdown notebooks when navigation unmounts the model: %s', async (unmount) => {
        const createNotebookSpy = mockCreateNotebook()
        logic.actions.receiveNotebookUpdate(SCRATCHPAD_NOTEBOOK)
        const retryImport = retryImportUtils.retryImport
        jest.spyOn(retryImportUtils, 'retryImport').mockImplementationOnce(async (factory) => {
            if (unmount) {
                logic.unmount()
                expect(logic.isMounted()).toBe(false)
            }
            return retryImport(factory)
        })

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
        }).toDispatchActions([
            (action) => {
                if (action.type !== logic.actionTypes.createNotebookSuccess) {
                    return false
                }
                expect(action.payload.notebooks).toEqual([
                    expect.objectContaining({ short_id: 'created-notebook' }),
                    SCRATCHPAD_NOTEBOOK,
                ])
                return true
            },
        ])

        const content = createNotebookSpy.mock.calls[0][0]?.content
        expect(content).toEqual(buildMarkdownNotebookContent(getMarkdownNotebookMarkdown(content)))
        expect(getMarkdownNotebookMarkdown(content)).toContain('# Activation')
        expect(getMarkdownNotebookMarkdown(content)).toContain('<Query')
        expect(getMarkdownNotebookMarkdown(content)).toContain('"kind":"HogQLQuery"')
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
