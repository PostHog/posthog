import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { INITIAL_RETRY_DELAY_MS } from 'lib/api-stream'
import { POLL_JITTER_RATIO } from 'lib/wizard-sync/pollLoop'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { NotebookType } from '../types'
import { buildMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'

const SHORT_ID = 'stream-reconnect'
const MARKDOWN = '# Title'

const notebookFixture = {
    id: 'notebook-id',
    short_id: SHORT_ID,
    title: 'Stream reconnect',
    content: buildMarkdownNotebookContent(MARKDOWN),
    text_content: MARKDOWN,
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

const updateMessage = { id: '1-0', event: 'update', data: '', retry: undefined }

describe('notebook markdown stream reconnect', () => {
    let logic: ReturnType<typeof notebookLogic.build>
    let collabStream: jest.SpyInstance
    let captureException: jest.SpyInstance
    let options: CollabStreamOptions
    let failStream: (error: unknown) => void

    beforeEach(async () => {
        localStorage.clear()
        useMocks({
            get: {
                [`/api/projects/@current/notebooks/${SHORT_ID}/`]: () => [200, notebookFixture],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/`]: () => [200, notebookFixture],
                [`/api/projects/:project_id/notebooks/${SHORT_ID}/kernel/status/`]: () => [200, { backend: null }],
            },
        })
        initKeaTests()
        captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)

        // Keeps the connection open, so the only reconnects are the ones the logic asks for.
        collabStream = jest.spyOn(api.notebooks, 'collabStream').mockImplementation((_shortId, opts) => {
            options = opts
            return new Promise<void>((_resolve, reject) => {
                failStream = reject
            })
        })

        logic = notebookLogic({ shortId: SHORT_ID, mode: 'notebook' })
        logic.mount()
        logic.actions.loadNotebook()
        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess']).toFinishAllListeners()
        expect(collabStream).toHaveBeenCalledTimes(1)

        // Pins the reconnect spread to its midpoint, which is the plain backoff step.
        jest.spyOn(Math, 'random').mockReturnValue(0.5)
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    // The per-engine wordings live in `lib/api-error.test.ts`. This only proves the stream asks
    // the shared classifier instead of reporting whatever it is handed.
    it('treats a dropped connection as a disconnect rather than an exception', () => {
        options.onError(new TypeError('network error'))

        expect(captureException).not.toHaveBeenCalled()
    })

    it('reports a stream failure the server is at fault for', () => {
        options.onError(new ApiError('Request failed with status 500', 500))

        expect(captureException).toHaveBeenCalledTimes(1)
    })

    // The returned number is how long fetch-event-source waits before it reopens the stream.
    // Returning nothing leaves its 1s default, which is the retry loop this guards against.
    it('backs off further on each failure and stops at the ceiling', () => {
        const delays = Array.from({ length: 7 }, () => options.onError(new TypeError('network error')))

        expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000])
    })

    // Notebooks dropped by one outage must not arrive back at the stream admission cap together.
    it('spreads each delay around the backoff step', () => {
        jest.spyOn(Math, 'random').mockReturnValue(0)
        expect(options.onError(new TypeError('network error'))).toBe(INITIAL_RETRY_DELAY_MS * (1 - POLL_JITTER_RATIO))

        jest.spyOn(Math, 'random').mockReturnValue(1)
        expect(options.onError(new TypeError('network error'))).toBe(
            INITIAL_RETRY_DELAY_MS * 2 * (1 + POLL_JITTER_RATIO)
        )
    })

    it('starts the backoff again once the connection delivers a message', () => {
        options.onError(new TypeError('network error'))
        options.onError(new TypeError('network error'))

        options.onMessage(updateMessage)

        expect(options.onError(new TypeError('network error'))).toBe(1000)
    })

    // The server rotates a working stream, so that close reopens at once.
    it('reopens at once when a close follows a delivered message', async () => {
        jest.useFakeTimers()

        options.onMessage(updateMessage)
        options.onClose?.()
        jest.advanceTimersByTime(0)
        await Promise.resolve()

        expect(collabStream).toHaveBeenCalledTimes(2)
    })

    // A backend that ends the body straight away reads as a clean close, so reopening at once
    // would loop as fast as the server can close.
    it('backs off when a close delivered nothing', async () => {
        jest.useFakeTimers()

        options.onClose?.()
        jest.advanceTimersByTime(999)
        await Promise.resolve()
        expect(collabStream).toHaveBeenCalledTimes(1)

        jest.advanceTimersByTime(1)
        await Promise.resolve()
        expect(collabStream).toHaveBeenCalledTimes(2)
    })

    it('reopens the stream once when a failure reaches both the close callback and the promise', async () => {
        jest.useFakeTimers()

        options.onMessage(updateMessage)
        options.onClose?.()
        failStream(new TypeError('network error'))
        await Promise.resolve()
        jest.advanceTimersByTime(1000)

        expect(collabStream).toHaveBeenCalledTimes(2)
    })
})
