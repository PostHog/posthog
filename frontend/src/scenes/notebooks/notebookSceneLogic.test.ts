import { expectLogic } from 'kea-test-utils'

import { MaxContextType } from 'scenes/max/maxTypes'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { notebookLogic } from './Notebook/notebookLogic'
import { notebookSceneLogic } from './notebookSceneLogic'
import type { NotebookType } from './types'

jest.mock('./Notebook/migrations/migrate', () => ({
    migrate: jest.fn(async (notebook) => notebook),
}))

const SHORT_ID = 'kgL54UTP'
const NOTEBOOK_TITLE = 'Revenue notebook'

const notebook: NotebookType = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: NOTEBOOK_TITLE,
    content: {
        type: 'doc',
        content: [],
    },
    text_content: '',
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2026-01-01T00:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

describe('notebookSceneLogic', () => {
    let logic: ReturnType<typeof notebookSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/projects/:team_id/notebooks/${SHORT_ID}/`]: () => [200, notebook],
                '/api/projects/:team_id/notebooks/:short_id/kernel/status/': () => [200, null],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('exposes the open notebook to Max context', async () => {
        logic = notebookSceneLogic({ shortId: SHORT_ID })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions([notebookLogic({ shortId: SHORT_ID }).actionTypes.loadNotebookSuccess])
            .toMatchValues({
                maxContext: [
                    {
                        type: MaxContextType.NOTEBOOK,
                        data: {
                            short_id: SHORT_ID,
                            title: NOTEBOOK_TITLE,
                        },
                    },
                ],
            })
    })

    it('does not expose a new notebook to Max context', () => {
        logic = notebookSceneLogic({ shortId: 'new' })
        logic.mount()

        expect(logic.values.maxContext).toEqual([])
    })
})
