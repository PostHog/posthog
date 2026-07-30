import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { NotebookTarget, NotebookType } from 'scenes/notebooks/types'

import { notebooksModel } from '~/models/notebooksModel'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NOTEBOOK_TEMPLATES } from './notebookTemplates'
import { notebookTemplatesLogic } from './notebookTemplatesLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

describe('notebookTemplatesLogic', () => {
    let logic: ReturnType<typeof notebookTemplatesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = notebookTemplatesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('creates a notebook from the picked template markdown', async () => {
        const createNotebookSpy = mockCreateNotebook()
        const template = NOTEBOOK_TEMPLATES[1]

        await expectLogic(logic, () => {
            logic.actions.createNotebookFromTemplate(template.short_id)
        })
            .toDispatchActions([
                notebooksModel.actionCreators.createNotebook(
                    NotebookTarget.Scene,
                    template.title,
                    undefined,
                    undefined,
                    undefined,
                    template.markdown,
                    template.short_id
                ),
            ])
            .toDispatchActions(notebooksModel, ['createNotebookSuccess'])

        expect(createNotebookSpy.mock.calls[0][0]?.content).toEqual(buildMarkdownNotebookContent(template.markdown))
        expect(logic.values.creatingTemplate).toBeNull()
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
