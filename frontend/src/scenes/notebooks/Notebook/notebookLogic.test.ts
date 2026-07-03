import { JSONContent } from '@tiptap/core'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookType } from '../types'
import { SYNC_DELAY, notebookLogic } from './notebookLogic'

// Skip the API-driven query upgrade step inside migrate — fixture content has no
// insight nodes, and migrate's per-node walk is out of scope for this test.
jest.mock('./migrations/migrate', () => {
    const actual = jest.requireActual('./migrations/migrate')
    return {
        ...actual,
        migrate: jest.fn(async (notebook) => notebook),
    }
})

const SHORT_ID = 'test-stale-save'

const doc = (text: string): JSONContent => ({
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
})

const notebookFixture = (version: number, text: string): NotebookType =>
    ({
        id: 'notebook-id',
        short_id: SHORT_ID,
        title: 'Test',
        content: doc(text),
        text_content: text,
        version,
        deleted: false,
        is_template: false,
        user_access_level: AccessControlLevel.Editor,
        created_at: '2025-01-01T00:00:00Z',
        created_by: null,
        last_modified_at: '2025-01-01T00:00:00Z',
        last_modified_by: null,
    }) as unknown as NotebookType

describe('notebookLogic stale-draft saves', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let serverNotebook: NotebookType
    let apiUpdateSpy: jest.SpyInstance

    beforeEach(() => {
        serverNotebook = notebookFixture(1, 'server v1')
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, serverNotebook],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/`]: () => [200, serverNotebook],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/kernel/status/`]: () => [200, { backend: null }],
            },
        })
        initKeaTests()
        // collabStream opens an SSE connection that never resolves in production —
        // resolve immediately in tests so the listener doesn't dangle.
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)
        // Server-side optimistic concurrency: accept only when the submitted version
        // matches the server head, exactly like the backend's select_for_update check.
        apiUpdateSpy = jest.spyOn(api.notebooks, 'update').mockImplementation(async (_id, data) => {
            if (data.version === serverNotebook.version) {
                serverNotebook = { ...serverNotebook, ...data, version: serverNotebook.version + 1 } as NotebookType
                return serverNotebook
            }
            const conflict: any = new Error('Someone else edited the Notebook')
            conflict.status = 409
            conflict.code = 'conflict'
            throw conflict
        })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('saves a stale draft against its base version so a concurrent edit conflicts instead of being clobbered', async () => {
        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        expect(logic.values.notebook!.version).toBe(1)

        // The user starts a draft based on v1. Autosave is paused while we arrange
        // the concurrent edit so the debounce can't fire mid-setup.
        logic.actions.setAutosavePaused(true)
        logic.actions.setLocalContent(doc('local draft based on v1'))

        // Meanwhile another writer saves v2 and the periodic poll refreshes this
        // tab's notebook (version included) without touching the local draft.
        serverNotebook = notebookFixture(2, 'external edit v2')
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        expect(logic.values.notebook!.version).toBe(2)
        expect(logic.values.localContent).toEqual(doc('local draft based on v1'))

        // The user keeps typing; the autosave fires with the stale draft.
        logic.actions.setAutosavePaused(false)
        logic.actions.setLocalContent(doc('local draft based on v1'))
        await expectLogic(logic)
            .delay(SYNC_DELAY + 100)
            .toFinishAllListeners()

        // The save must carry the version the draft was based on (1), not the
        // refreshed head (2) — otherwise the server accepts it and the external
        // edit is silently destroyed.
        expect(apiUpdateSpy).toHaveBeenCalledWith(SHORT_ID, expect.objectContaining({ version: 1 }))
        // With the honest base version the server 409s and the existing conflict
        // flow takes over instead of clobbering.
        expect(logic.values.conflictWarningVisible).toBe(true)
        expect(logic.values.localContent).toBeNull()
    })
})
