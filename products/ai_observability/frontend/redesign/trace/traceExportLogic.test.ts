import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceExportApi } from '../../generated/api.schemas'
import { makeTraceResource } from './testFixtures'
import { toExportedAsset, traceExportLogic } from './traceExportLogic'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const EXPORT_URL = '/api/projects/:team_id/ai_observability/traces/:id/exports/'
const EXPORT_STATUS_URL = '/api/projects/:team_id/ai_observability/traces/:id/exports/:export_id/'
const EXPORT_CONTENT_URL = '/api/projects/:team_id/ai_observability/traces/:id/exports/:export_id/content/'
const EXPORT_FILE = { trace: { id: 'trace-1' }, truncated: false, nodes: [] }
const EXPORT_FILE_TEXT = JSON.stringify(EXPORT_FILE)
const OVERSIZED_FILE = { padding: 'x'.repeat(5_000_000) }

class FakeClipboardItem {
    constructor(readonly items: Record<string, Promise<Blob>>) {}
}

function makeTraceExport(overrides: Partial<TraceExportApi> = {}): TraceExportApi {
    return {
        id: 7,
        status: 'pending',
        filename: 'trace-1-2026-09-01-101500.json',
        createdAt: '2026-09-01T10:20:00Z',
        expiresAfter: '2026-09-08T10:20:00Z',
        exception: null,
        ...overrides,
    }
}

describe('traceExportLogic', () => {
    const props = { traceId: 'trace-1', timestampHint: null }
    let createdExport: TraceExportApi = makeTraceExport()
    let exportBodies: unknown[] = []
    let statusRequests = 0
    let exportFile: object = EXPORT_FILE
    let contentPurposes: (string | null)[] = []
    let clipboardText: string | null = null
    const clipboardWrite = jest.fn(async ([item]: FakeClipboardItem[]): Promise<void> => {
        clipboardText = await (await item.items['text/plain']).text()
    })

    beforeEach(() => {
        createdExport = makeTraceExport()
        exportBodies = []
        statusRequests = 0
        exportFile = EXPORT_FILE
        contentPurposes = []
        clipboardText = null
        clipboardWrite.mockClear()
        Object.defineProperty(globalThis, 'ClipboardItem', { value: FakeClipboardItem, configurable: true })
        Object.defineProperty(navigator, 'clipboard', { value: { write: clipboardWrite }, configurable: true })
        useMocks({
            get: {
                [TRACE_URL]: () => [200, makeTraceResource()],
                '/api/projects/:team_id/ai_observability/traces/:id/evaluations/': () => [200, { results: [] }],
                [EXPORT_STATUS_URL]: () => {
                    statusRequests += 1
                    return [200, makeTraceExport({ status: 'complete' })]
                },
                [EXPORT_CONTENT_URL]: ({ request }) => {
                    contentPurposes.push(new URL(request.url).searchParams.get('purpose'))
                    return [200, exportFile]
                },
            },
            post: {
                [EXPORT_URL]: async ({ request }) => {
                    exportBodies.push(await request.json())
                    return [201, createdExport]
                },
            },
        })
        initKeaTests()
        jest.spyOn(lemonToast, 'info').mockImplementation(() => 'toast')
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
        jest.spyOn(posthog, 'capture')
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    test.each([
        ['pending', makeTraceExport(), { has_content: false, exception: undefined }],
        ['complete', makeTraceExport({ status: 'complete' }), { has_content: true, exception: undefined }],
        ['failed', makeTraceExport({ status: 'failed', exception: 'Boom' }), { has_content: false, exception: 'Boom' }],
    ])('toExportedAsset maps a %s export', (_status, traceExport, expected) => {
        expect(toExportedAsset(traceExport)).toMatchObject({ id: 7, export_format: 'application/json', ...expected })
    })

    test('exportTrace sends the trace time and hands the export to the exports panel', async () => {
        exportsLogic.mount()
        await expectLogic(traceViewLogic(props), () => {
            traceViewLogic(props).mount()
        }).toFinishAllListeners()
        const logic = traceExportLogic(props)
        logic.mount()
        const tracked: ReturnType<typeof exportsLogic.actionCreators.trackExport>['payload'][] = []

        await expectLogic(logic, () => logic.actions.exportTrace()).toDispatchActions([
            'exportTraceSuccess',
            (action) => {
                const isTrackExport = action.type === exportsLogic.actionTypes.trackExport
                if (isTrackExport) {
                    tracked.push({
                        exportedAsset: action.payload.exportedAsset,
                        fetchLatest: action.payload.fetchLatest,
                    })
                }
                return isTrackExport
            },
        ])

        expect(exportBodies).toEqual([{ timestamp_hint: '2026-09-01T10:15:00Z' }])
        const [{ exportedAsset, fetchLatest }] = tracked
        expect(exportedAsset).toEqual(toExportedAsset(createdExport))
        await expect(fetchLatest?.()).resolves.toMatchObject({ id: 7, has_content: true })
        expect(statusRequests).toBe(1)
        expect(lemonToast.info).toHaveBeenCalledTimes(1)
    })

    test('an export that failed to start shows its reason and is not tracked', async () => {
        createdExport = makeTraceExport({ status: 'failed', exception: 'The export could not be started. Try again.' })
        exportsLogic.mount()
        const logic = traceExportLogic(props)
        logic.mount()

        await expectLogic(logic, () => logic.actions.exportTrace())
            .toDispatchActions(['exportTraceSuccess'])
            .toNotHaveDispatchedActions([exportsLogic.actionTypes.trackExport])

        expect(lemonToast.error).toHaveBeenCalledWith('The export could not be started. Try again.')
    })

    async function mountForCopy(): Promise<ReturnType<typeof traceExportLogic.build>> {
        exportsLogic.mount()
        await expectLogic(traceViewLogic(props), () => {
            traceViewLogic(props).mount()
        }).toFinishAllListeners()
        const logic = traceExportLogic(props)
        logic.mount()
        return logic
    }

    // Safari and Firefox drop a clipboard write that starts after an await, so it has to begin in the click itself.
    // Hiding the page mid-copy pauses disposables by default, which would abort the read.
    test('copyTrace starts the clipboard write in the click and fills it with the exported file, even if the tab is hidden', async () => {
        const logic = await mountForCopy()

        logic.actions.copyTrace()
        expect(clipboardWrite).toHaveBeenCalledTimes(1)
        expect(logic.values.traceCopying).toBe(true)
        Object.defineProperty(document, 'hidden', { value: true, configurable: true })
        try {
            document.dispatchEvent(new Event('visibilitychange'))
            await expectLogic(logic).toDispatchActions(['copyTraceFinished'])
        } finally {
            Object.defineProperty(document, 'hidden', { value: false, configurable: true })
        }

        expect(clipboardText).toEqual(EXPORT_FILE_TEXT)
        expect(statusRequests).toBe(1)
        expect(contentPurposes).toEqual(['copy'])
        expect(logic.values.traceCopying).toBe(false)
        expect(posthog.capture).toHaveBeenCalledWith('llma trace export copied', {
            size_bytes: EXPORT_FILE_TEXT.length,
            fallback: false,
        })
    })

    test.each([
        {
            name: 'a refused clipboard write offers a copy button',
            setup: (): void => {
                createdExport = makeTraceExport({ status: 'complete' })
                clipboardWrite.mockRejectedValueOnce(new Error('NotAllowedError'))
            },
            toast: 'info' as const,
            message: 'The trace is ready to copy.',
            button: 'Copy',
            event: null,
        },
        {
            name: 'an oversized trace offers to download the same export',
            setup: (): void => {
                createdExport = makeTraceExport({ status: 'complete' })
                exportFile = OVERSIZED_FILE
            },
            toast: 'info' as const,
            message: "This trace is larger than 5 MB, so it can't be copied. Download it as a JSON file instead.",
            button: 'Download',
            event: 'too_large',
        },
        {
            name: 'a failed export shows its reason',
            setup: (): void => {
                createdExport = makeTraceExport({ status: 'failed', exception: 'This trace is no longer available.' })
            },
            toast: 'error' as const,
            message: 'This trace is no longer available.',
            button: undefined,
            event: 'export_failed',
        },
    ])('$name', async ({ setup, toast, message, button, event }) => {
        setup()
        const logic = await mountForCopy()

        await expectLogic(logic, () => logic.actions.copyTrace()).toDispatchActions(['copyTraceFinished'])

        expect(lemonToast[toast]).toHaveBeenCalledWith(message, ...(button ? [expect.anything()] : []))
        const options = jest.mocked(lemonToast[toast]).mock.calls[0][1] as { button?: { label: string } } | undefined
        expect(options?.button?.label).toEqual(button)
        expect(posthog.capture).not.toHaveBeenCalledWith('llma trace export copied', expect.anything())
        if (event) {
            expect(posthog.capture).toHaveBeenCalledWith('llma trace export copy failed', { reason: event })
        }
    })

    test('the download button on the oversized toast downloads the export the copy wrote', async () => {
        createdExport = makeTraceExport({ status: 'complete' })
        exportFile = OVERSIZED_FILE
        const logic = await mountForCopy()
        await expectLogic(logic, () => logic.actions.copyTrace()).toDispatchActions(['copyTraceFinished'])
        const options = jest.mocked(lemonToast.info).mock.calls[0][1] as { button: { action: () => void } }

        await expectLogic(exportsLogic, () => options.button.action()).toDispatchActions([
            exportsLogic.actionCreators.downloadExport(toExportedAsset(createdExport)),
        ])
    })

    test('a browser without clipboard writes shows a failed export without an unhandled rejection', async () => {
        Object.defineProperty(globalThis, 'ClipboardItem', { value: undefined, configurable: true })
        createdExport = makeTraceExport({ status: 'failed', exception: 'This trace is no longer available.' })
        const unhandled: unknown[] = []
        const recordUnhandled = (reason: unknown): void => {
            unhandled.push(reason)
        }
        process.on('unhandledRejection', recordUnhandled)
        try {
            const logic = await mountForCopy()
            await expectLogic(logic, () => logic.actions.copyTrace()).toDispatchActions(['copyTraceFinished'])
            await new Promise((resolve) => setTimeout(resolve, 0))
        } finally {
            process.off('unhandledRejection', recordUnhandled)
        }

        expect(lemonToast.error).toHaveBeenCalledWith('This trace is no longer available.')
        expect(unhandled).toEqual([])
    })
})
