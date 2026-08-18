import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'

const SHORT_ID = 'test-markdown-stream'
const BASE_MARKDOWN = '# Title'

const notebook: NotebookType = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Test',
    content: buildMarkdownNotebookContent(BASE_MARKDOWN),
    text_content: BASE_MARKDOWN,
    version: 1,
    deleted: false,
    is_template: false,
    user_access_level: AccessControlLevel.Editor,
    created_at: '2025-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2025-01-01T00:00:00Z',
    last_modified_by: null,
} as unknown as NotebookType

type CollabStreamOptions = Parameters<typeof api.notebooks.collabStream>[1]

describe('notebookLogic markdown stream reconnect', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let lastOptions: CollabStreamOptions

    beforeEach(async () => {
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, notebook],
                [`/api/projects/:project_id/notebooks/:short_id/kernel/status/`]: () => [200, { backend: null }],
            },
        })
        localStorage.clear()
        initKeaTests()

        // Capture the callbacks the logic hands to the stream, then keep the request pending so
        // the only reconnects are the ones the backoff schedules.
        jest.spyOn(api.notebooks, 'collabStream').mockImplementation((_id, options) => {
            lastOptions = options
            return new Promise<void>(() => {})
        })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('treats a network failure as a disconnect and reconnects on a delay instead of reporting it', async () => {
        const captureException = jest.spyOn(posthog, 'captureException')
        jest.useFakeTimers()

        try {
            lastOptions.onError(new TypeError('Failed to fetch'))
        } catch {
            // onError rethrows to stop fetch-event-source's own retry; the backoff owns reconnection.
        }

        expect(captureException).not.toHaveBeenCalled()
        expect(api.notebooks.collabStream).toHaveBeenCalledTimes(1)

        jest.advanceTimersByTime(1_000)
        await Promise.resolve()
        expect(api.notebooks.collabStream).toHaveBeenCalledTimes(2)
    })

    it('reports a non-network stream failure as an exception', () => {
        const captureException = jest.spyOn(posthog, 'captureException')

        try {
            lastOptions.onError(new Error('unexpected stream fault'))
        } catch {
            // rethrow is expected
        }

        expect(captureException).toHaveBeenCalledTimes(1)
    })

    it('schedules one reconnect when a failure trips both the error and close paths', async () => {
        jest.useFakeTimers()

        try {
            lastOptions.onError(new TypeError('Failed to fetch'))
        } catch {
            // rethrow is expected
        }
        lastOptions.onClose?.()

        jest.advanceTimersByTime(1_000)
        await Promise.resolve()
        expect(api.notebooks.collabStream).toHaveBeenCalledTimes(2)
    })
})
