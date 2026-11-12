import { expectLogic } from 'kea-test-utils'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import * as retryImportUtils from 'lib/utils/retryImport'
import { buildMarkdownNotebookContent, getMarkdownNotebookMarkdown } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { NotebookNodeType, NotebookTarget } from 'scenes/notebooks/types'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from 'products/notebooks/frontend/generated/api'
import type { NotebookApi } from 'products/notebooks/frontend/generated/api.schemas'

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

        const content = createNotebookSpy.mock.calls[0][1]?.content as JSONContent
        expect(content).toEqual(buildMarkdownNotebookContent(getMarkdownNotebookMarkdown(content)))
        expect(getMarkdownNotebookMarkdown(content)).toContain('# Activation')
        expect(getMarkdownNotebookMarkdown(content)).toContain('<Query')
        expect(getMarkdownNotebookMarkdown(content)).toContain('"kind":"HogQLQuery"')
    })

    it('opens the existing notebook when its artifact was already saved', async () => {
        mockCreateNotebook().mockRejectedValue({ status: 400, code: 'unique', attr: 'short_id' })
        const existing = { ...savedNotebook, short_id: 'reportA', title: 'Saved report' }
        const retrieve = jest.spyOn(generatedApi, 'notebooksRetrieve').mockResolvedValue(existing)
        logic.actions.receiveNotebookUpdate({
            id: existing.id,
            short_id: existing.short_id,
            title: existing.title,
            created_at: existing.created_at,
            created_by: null,
        })

        await expectLogic(logic, () => {
            logic.actions.createNotebook(NotebookTarget.Scene, 'New title', undefined, undefined, 'reportA')
        }).toDispatchActions(['createNotebookSuccess'])

        expect(retrieve).toHaveBeenCalledWith(String(logic.values.currentProjectId), 'reportA')
        expect(logic.values.notebooks).toEqual([existing])
    })

    it('preserves access checks when reopening an already saved artifact', async () => {
        mockCreateNotebook().mockRejectedValue({ status: 400, code: 'unique', attr: 'short_id' })
        jest.spyOn(generatedApi, 'notebooksRetrieve').mockRejectedValue({ status: 403, detail: 'Access denied' })

        await expectLogic(logic, () => {
            logic.actions.createNotebook(NotebookTarget.Scene, 'New title', undefined, undefined, 'reportA')
        }).toDispatchActions(['createNotebookFailure'])

        expect(logic.values.notebooks).toEqual([])
    })
})

const savedNotebook = {
    id: 'created-notebook',
    short_id: 'created-notebook',
    created_at: '2026-06-29T00:00:00Z',
    created_by: {
        id: 1,
        uuid: 'test-user',
        distinct_id: 'test-user',
        first_name: 'Test',
        email: 'test@example.com',
        hedgehog_config: null,
    },
    last_modified_at: '2026-06-29T00:00:00Z',
    last_modified_by: {
        id: 1,
        uuid: 'test-user',
        distinct_id: 'test-user',
        first_name: 'Test',
        email: 'test@example.com',
        hedgehog_config: null,
    },
    parent_resource: null,
    version: 1,
    content: null,
    user_access_level: 'editor',
} satisfies NotebookApi

function mockCreateNotebook(): jest.SpyInstance<
    ReturnType<typeof generatedApi.notebooksCreate>,
    Parameters<typeof generatedApi.notebooksCreate>
> {
    return jest.spyOn(generatedApi, 'notebooksCreate').mockImplementation(async (_projectId, data) => ({
        ...savedNotebook,
        content: data?.content ?? null,
        title: data?.title,
    }))
}
