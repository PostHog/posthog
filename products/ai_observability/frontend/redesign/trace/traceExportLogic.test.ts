import { expectLogic } from 'kea-test-utils'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceExportApi } from '../../generated/api.schemas'
import { makeTraceResource } from './adapter/testFixtures'
import { toExportedAsset, traceExportLogic } from './traceExportLogic'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const EXPORT_URL = '/api/projects/:team_id/ai_observability/traces/:id/exports/'
const EXPORT_STATUS_URL = '/api/projects/:team_id/ai_observability/traces/:id/exports/:export_id/'

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

    beforeEach(() => {
        createdExport = makeTraceExport()
        exportBodies = []
        statusRequests = 0
        useMocks({
            get: {
                [TRACE_URL]: () => [200, makeTraceResource()],
                '/api/projects/:team_id/ai_observability/traces/:id/evaluations/': () => [200, { results: [] }],
                [EXPORT_STATUS_URL]: () => {
                    statusRequests += 1
                    return [200, makeTraceExport({ status: 'complete' })]
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
})
