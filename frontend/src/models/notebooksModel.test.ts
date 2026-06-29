import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { buildMarkdownNotebookContent, getMarkdownNotebookMarkdown } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { NotebookNodeType, NotebookTarget, NotebookType } from 'scenes/notebooks/types'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { notebooksModel } from './notebooksModel'

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

    it('creates rich notebooks when markdown notebooks are not enabled', async () => {
        const createNotebookSpy = mockCreateNotebook()

        await expectLogic(logic, () => {
            logic.actions.createNotebook(NotebookTarget.Scene, 'Activation')
        }).toDispatchActions(['createNotebookSuccess'])

        expect(createNotebookSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                title: 'Activation',
                content: {
                    type: 'doc',
                    content: [
                        {
                            type: 'heading',
                            attrs: { level: 1 },
                            content: [{ type: 'text', text: 'Activation' }],
                        },
                    ],
                },
            })
        )
    })

    it('creates markdown notebooks when markdown notebooks are enabled', async () => {
        const createNotebookSpy = mockCreateNotebook()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MARKDOWN_NOTEBOOKS], {
            [FEATURE_FLAGS.MARKDOWN_NOTEBOOKS]: true,
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
        }).toDispatchActions(['createNotebookSuccess'])

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
