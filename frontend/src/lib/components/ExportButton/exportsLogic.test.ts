import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { ExportedAssetType, ExporterFormat, InsightShortId, SidePanelTab } from '~/types'

import {
    ExportNudgeCandidate,
    captureExportNudgeCheckFailed,
    lookUpExportNudge,
    resolveExportNudgeEligibility,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'
import {
    ExportNudgeMessage,
    claimExportNudgeMessage,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/ExportNudgeToast'

import { downloadExportedAsset } from './exporter'
import { exportsLogic, pickPollDelayMs } from './exportsLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    // promise() passes the underlying promise straight through so the loader's side effects still run.
    lemonToast: {
        info: jest.fn(),
        success: jest.fn(),
        error: jest.fn(),
        dismiss: jest.fn(),
        promise: jest.fn((p) => p),
        updateToSuccess: jest.fn(),
        isActive: jest.fn(() => true),
    },
}))
jest.mock('./exporter', () => ({
    ...jest.requireActual('./exporter'),
    downloadExportedAsset: jest.fn(),
}))
// The eligibility rules themselves are covered by exportNudgeLogic's tests.
jest.mock('products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic', () => ({
    lookUpExportNudge: jest.fn(() => ({ status: 'unknown' })),
    resolveExportNudgeEligibility: jest.fn(async () => null),
    captureExportNudgeCheckFailed: jest.fn(),
    exportNudgeEventProperties: jest.fn(() => ({})),
}))
jest.mock('products/subscriptions/frontend/components/Subscriptions/exportNudge/ExportNudgeToast', () => ({
    claimExportNudgeMessage: jest.fn(() => null),
}))

// The nudge body stands in as an opaque element that echoes the headline it was rendered under,
// which is what distinguishes the toast's states.
const NUDGE_MESSAGE: ExportNudgeMessage = (headline, _toastId, action) =>
    `nudge:${headline}${action ? ` +${action.label}` : ''}`

const DASHBOARD_SUBJECT = { kind: 'dashboard' as const, dashboardId: 7 }
const INSIGHT_SHORT_ID = '11' as InsightShortId

const asset = (overrides: Partial<ExportedAssetType> = {}): ExportedAssetType => ({
    id: 1,
    export_format: ExporterFormat.CSV,
    has_content: false,
    filename: 'export.csv',
    created_at: '2026-05-11T19:00:00Z',
    ...overrides,
})

describe('exportsLogic', () => {
    describe('pickPollDelayMs', () => {
        it('returns the default delay when nothing is pending', () => {
            expect(pickPollDelayMs([asset({ has_content: true })])).toBe(10000)
        })

        it('returns the default delay when at least one pending asset is fast', () => {
            expect(
                pickPollDelayMs([
                    asset({ id: 1, export_format: ExporterFormat.MP4 }),
                    asset({ id: 2, export_format: ExporterFormat.CSV }),
                ])
            ).toBe(10000)
        })

        it('backs off when every pending asset is a long-running format', () => {
            expect(
                pickPollDelayMs([
                    asset({ id: 1, export_format: ExporterFormat.MP4 }),
                    asset({ id: 2, export_format: ExporterFormat.WEBM }),
                ])
            ).toBe(30000)
        })

        it('ignores assets that already have content or an exception when deciding', () => {
            expect(
                pickPollDelayMs([
                    asset({ id: 1, export_format: ExporterFormat.CSV, has_content: true }),
                    asset({ id: 2, export_format: ExporterFormat.MP4 }),
                ])
            ).toBe(30000)
        })
    })

    describe('startReplayExport', () => {
        let logic: ReturnType<typeof exportsLogic.build>
        let startExportSpy: jest.SpyInstance

        beforeEach(() => {
            initKeaTests()
            logic = exportsLogic()
            logic.mount()
            startExportSpy = jest.spyOn(logic.actions, 'startExport')
        })

        afterEach(() => {
            startExportSpy.mockRestore()
        })

        it.each([
            { options: { skip_inactivity: true as const }, expected: true },
            { options: { skip_inactivity: false as const }, expected: false },
            { options: {}, expected: true },
        ])('sets skip_inactivity from export options', ({ options, expected }) => {
            logic.actions.startReplayExport('session-abc', ExporterFormat.MP4, 0, 3600, undefined, options)

            expect(startExportSpy).toHaveBeenCalledTimes(1)
            expect(startExportSpy.mock.calls[0][0].export_context?.skip_inactivity).toBe(expected)
        })
    })

    describe('createExport toast', () => {
        let logic: ReturnType<typeof exportsLogic.build>

        beforeEach(() => {
            jest.clearAllMocks()
            jest.mocked(lookUpExportNudge).mockReturnValue({ status: 'unknown' })
            jest.mocked(resolveExportNudgeEligibility).mockResolvedValue(null)
            jest.mocked(claimExportNudgeMessage).mockReturnValue(null)
            jest.mocked(lemonToast.isActive).mockReturnValue(true)
            initKeaTests()
            logic = exportsLogic()
            logic.mount()
            jest.spyOn(api.exports, 'list').mockResolvedValue({ results: [], count: 0 } as any)
        })

        afterEach(() => {
            logic.unmount()
        })

        // Let the fire-and-forget IIFE in the createExport loader run to settlement.
        const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

        // A macrotask sentinel always loses to an already-settled promise, so a regression that
        // leaves the export toast pending reports UNSETTLED instead of timing the test out.
        const UNSETTLED = 'unsettled'
        const settledValueOf = async (promise: Promise<any>): Promise<any> =>
            await Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(UNSETTLED), 0))])

        const createCases: {
            label: string
            response?: ExportedAssetType
            rejectWith?: Error
            format: ExporterFormat
            settles: { resolved: string } | { rejected: string }
            expectsDownload: boolean
            expectsViewExportsButton: boolean
            freshIds: number[]
            expectsPanelOpen: boolean
        }[] = [
            {
                label: 'async export resolves to "Export started" and is tracked as undownloaded',
                response: asset({ id: 11, export_format: ExporterFormat.MP4, has_content: false }),
                format: ExporterFormat.MP4,
                settles: { resolved: 'Export started' },
                expectsDownload: false,
                expectsViewExportsButton: true,
                freshIds: [11],
                expectsPanelOpen: true,
            },
            {
                label: 'blocking export with content is downloaded and resolves to "Export complete!"',
                response: asset({ id: 12, export_format: ExporterFormat.CSV, has_content: true }),
                format: ExporterFormat.CSV,
                settles: { resolved: 'Export complete!' },
                expectsDownload: true,
                expectsViewExportsButton: false,
                freshIds: [],
                expectsPanelOpen: false,
            },
            {
                label: 'export that failed in the request rejects with the error',
                response: asset({ id: 13, export_format: ExporterFormat.MP4, exception: 'boom' }),
                format: ExporterFormat.MP4,
                settles: { rejected: 'Export failed: boom' },
                expectsDownload: false,
                expectsViewExportsButton: true,
                freshIds: [],
                expectsPanelOpen: false,
            },
            {
                label: 'create request that throws rejects with the error',
                rejectWith: new Error('network down'),
                format: ExporterFormat.MP4,
                settles: { rejected: 'Export failed: network down' },
                expectsDownload: false,
                expectsViewExportsButton: true,
                freshIds: [],
                expectsPanelOpen: false,
            },
        ]

        it.each(createCases)(
            '$label',
            async ({
                response,
                rejectWith,
                format,
                settles,
                expectsDownload,
                expectsViewExportsButton,
                freshIds,
                expectsPanelOpen,
            }) => {
                const createSpy = jest.spyOn(api.exports, 'create')
                if (rejectWith) {
                    createSpy.mockRejectedValue(rejectWith)
                } else {
                    createSpy.mockResolvedValue(response!)
                }

                logic.actions.createExport({ exportData: { export_format: format } })
                await flush()

                // The loading spinner is driven by lemonToast.promise, so the user always sees "Preparing export…".
                expect(lemonToast.promise).toHaveBeenCalledWith(
                    expect.any(Promise),
                    expect.objectContaining({ pending: 'Preparing export…' }),
                    expect.objectContaining({ toastId: expect.any(String) })
                )
                // The button rides every frame the toast has, including the pending one, where a
                // synchronous export's row does not exist client-side yet. Only a video render,
                // which lands in the panel minutes later, earns the link.
                const toastOptions = jest.mocked(lemonToast.promise).mock.calls[0][2]
                expect(toastOptions?.button?.label).toEqual(expectsViewExportsButton ? 'View exports' : undefined)
                const runPromise = jest.mocked(lemonToast.promise).mock.calls[0][0]
                if ('resolved' in settles) {
                    await expect(runPromise).resolves.toBe(settles.resolved)
                } else {
                    await expect(runPromise).rejects.toThrow(settles.rejected)
                }
                expect(jest.mocked(downloadExportedAsset).mock.calls).toEqual(expectsDownload ? [[response]] : [])
                // Only a nudge earns a toast that sits there until answered; everything else keeps
                // the settled toast react-toastify raised, which closes on its own.
                expect(lemonToast.updateToSuccess).not.toHaveBeenCalled()
                expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual(freshIds)
                // selectedTab is persisted across kea contexts, so assert the open+tab combination.
                expect(
                    sidePanelStateLogic.values.sidePanelOpen &&
                        sidePanelStateLogic.values.selectedTab === SidePanelTab.Exports
                ).toBe(expectsPanelOpen)
            }
        )

        it.each([
            ['a dashboard export', { dashboard: 7 }, [[{ kind: 'dashboard', dashboardId: 7 }]]],
            [
                'an insight export',
                { insight: 11, insightShortId: INSIGHT_SHORT_ID },
                [[{ kind: 'insight', insightShortId: INSIGHT_SHORT_ID }]],
            ],
            // A CSV of a data table, a recording render, a cohort: nothing to subscribe to.
            ['an export of anything else', {}, []],
        ])('resolves the subscribe nudge for %s', async (_label, exportSubject, expectedCalls) => {
            jest.spyOn(api.exports, 'create').mockResolvedValue(
                asset({ id: 17, export_format: ExporterFormat.PNG, has_content: true })
            )

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, ...exportSubject } })
            await flush()

            expect(jest.mocked(resolveExportNudgeEligibility).mock.calls).toEqual(expectedCalls)
        })

        it.each([ExporterFormat.CSV, ExporterFormat.XLSX])('leaves a %s export of an insight alone', async (format) => {
            // A subscription delivers a rendered image, so offering one to someone taking rows
            // would promise something other than what they just did.
            jest.spyOn(api.exports, 'create').mockResolvedValue(
                asset({ id: 19, export_format: format, has_content: true })
            )

            logic.actions.createExport({
                exportData: { export_format: format, insightShortId: INSIGHT_SHORT_ID },
            })
            await flush()

            expect(resolveExportNudgeEligibility).not.toHaveBeenCalled()
            expect(lookUpExportNudge).not.toHaveBeenCalled()
        })

        it('folds an eligible nudge into the toast a polled dashboard export completes with', async () => {
            jest.mocked(resolveExportNudgeEligibility).mockResolvedValue({
                subject: { kind: 'dashboard', dashboardId: 8 },
                name: null,
            })
            jest.mocked(claimExportNudgeMessage).mockReturnValue(NUDGE_MESSAGE)
            const pending = asset({ id: 18, export_format: ExporterFormat.PNG, dashboard: 8 })
            const finished = asset({ id: 18, export_format: ExporterFormat.PNG, has_content: true, dashboard: 8 })

            logic.actions.addFresh(pending)
            logic.actions.loadExportsSuccess([finished])
            await flush()

            expect(jest.mocked(resolveExportNudgeEligibility).mock.calls).toEqual([
                [{ kind: 'dashboard', dashboardId: 8 }],
            ])
            // The completion toast and its Download button are raised before the check runs, so a
            // slow check cannot delay the only signal a polled export gives.
            expect(lemonToast.success).toHaveBeenCalledWith(
                'Export complete!',
                expect.objectContaining({ button: expect.objectContaining({ label: 'Download' }) })
            )
            // The nudge then folds into that same toast, and the Download hand-off stays in the
            // standard button slot. An undelivered file plus an unanswered offer holds it open.
            const toastId = jest.mocked(lemonToast.success).mock.calls.at(-1)![1]!.toastId
            expect(lemonToast.updateToSuccess).toHaveBeenCalledWith(toastId, 'nudge:Export complete! +Download', {
                autoClose: false,
            })
        })

        it('builds the toast with the offer already in it when eligibility needs no request', async () => {
            // The scene has already loaded what the check needs, so the offer is in the first frame
            // the user sees and the toast is never rewritten to add it.
            jest.mocked(lookUpExportNudge).mockReturnValue({
                status: 'eligible',
                candidate: { subject: DASHBOARD_SUBJECT, name: 'Weekly numbers' },
            })
            jest.mocked(claimExportNudgeMessage).mockReturnValue(NUDGE_MESSAGE)
            jest.spyOn(api.exports, 'create').mockResolvedValue(
                asset({ id: 26, export_format: ExporterFormat.PNG, has_content: true, dashboard: 7 })
            )

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
            await flush()

            const messages = jest.mocked(lemonToast.promise).mock.calls[0][1]
            expect(messages.pending).toBe('nudge:Preparing export…')
            // Evaluated when the toast settles, so an offer followed while the export ran is gone by
            // then rather than being asked a second time.
            expect(typeof messages.success).toBe('function')
            expect((messages.success as (data?: string) => string)('Export complete!')).toBe('nudge:Export complete!')
            expect(resolveExportNudgeEligibility).not.toHaveBeenCalled()
            expect(lemonToast.updateToSuccess).not.toHaveBeenCalled()
            expect(claimExportNudgeMessage).toHaveBeenCalledTimes(1)
        })

        it('settles the export toast before the nudge check answers', async () => {
            // The file is already on disk once the create call returns, so a check that takes its
            // full timeout must not leave the exporter watching a spinner. Both variants pay this,
            // since eligibility is resolved before the experiment flag is ever read.
            let resolveEligibility: (candidate: ExportNudgeCandidate | null) => void = () => {}
            jest.mocked(resolveExportNudgeEligibility).mockReturnValue(
                new Promise((resolve) => {
                    resolveEligibility = resolve
                })
            )
            jest.mocked(claimExportNudgeMessage).mockReturnValue(NUDGE_MESSAGE)
            jest.spyOn(api.exports, 'create').mockResolvedValue(
                asset({ id: 27, export_format: ExporterFormat.PNG, has_content: true, dashboard: 7 })
            )

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
            await flush()

            const runPromise = jest.mocked(lemonToast.promise).mock.calls[0][0]
            expect(await settledValueOf(runPromise)).toBe('Export complete!')
            expect(jest.mocked(downloadExportedAsset)).toHaveBeenCalled()
            expect(claimExportNudgeMessage).not.toHaveBeenCalled()

            // The nudge then folds into that same toast rather than raising a second one, and is
            // claimed once.
            resolveEligibility({ subject: DASHBOARD_SUBJECT, name: null })
            await flush()

            expect(claimExportNudgeMessage).toHaveBeenCalledTimes(1)
            expect(lemonToast.info).not.toHaveBeenCalled()
            // The file downloaded itself, so nothing is owed and the offer alone does not hold the
            // toast open.
            expect(lemonToast.updateToSuccess).toHaveBeenCalledWith(
                jest.mocked(lemonToast.promise).mock.calls[0][2]?.toastId,
                'nudge:Export complete!',
                {}
            )
        })

        it('carries one toast from kickoff through to polled completion', async () => {
            // An async render acknowledges the kickoff, then lands minutes later. Both toasts are
            // about the same export, so the first must go when the second arrives.
            const rendering = asset({ id: 41, export_format: ExporterFormat.PNG, dashboard: 7 })
            jest.spyOn(api.exports, 'create').mockResolvedValue(rendering)

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
            await flush()
            const kickoffToastId = jest.mocked(lemonToast.promise).mock.calls[0][2]?.toastId

            logic.actions.loadExportsSuccess([{ ...rendering, has_content: true }])
            await flush()

            // Settled in place, so the acknowledgement does not close and animate a second toast in.
            expect(lemonToast.updateToSuccess).toHaveBeenCalledWith(
                kickoffToastId,
                'Export complete!',
                expect.objectContaining({ button: expect.objectContaining({ label: 'Download' }) })
            )
            expect(lemonToast.success).not.toHaveBeenCalled()
            expect(lemonToast.dismiss).not.toHaveBeenCalled()
        })

        it('raises a fresh toast when the kickoff toast is long gone', async () => {
            // A render that takes minutes outlives its acknowledgement, and updating a dismissed id
            // does nothing, so the completion has to raise a toast of its own.
            jest.mocked(lemonToast.isActive).mockReturnValue(false)
            const rendering = asset({ id: 43, export_format: ExporterFormat.MP4 })
            jest.spyOn(api.exports, 'create').mockResolvedValue(rendering)

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.MP4 } })
            await flush()
            logic.actions.loadExportsSuccess([{ ...rendering, has_content: true }])
            await flush()

            expect(jest.mocked(lemonToast.success).mock.calls).toHaveLength(1)
            expect(jest.mocked(lemonToast.success).mock.calls[0][1]?.toastId).toEqual(
                expect.stringContaining('export-complete-')
            )
        })

        it('claims the offer once across the kickoff and completion toasts', async () => {
            // Claiming twice reports two exposures for one export and asks the same person twice.
            jest.mocked(lookUpExportNudge).mockReturnValue({
                status: 'eligible',
                candidate: { subject: DASHBOARD_SUBJECT, name: 'Weekly numbers' },
            })
            jest.mocked(claimExportNudgeMessage).mockReturnValue(NUDGE_MESSAGE)
            const rendering = asset({ id: 42, export_format: ExporterFormat.PNG, dashboard: 7 })
            jest.spyOn(api.exports, 'create').mockResolvedValue(rendering)

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
            await flush()
            logic.actions.loadExportsSuccess([{ ...rendering, has_content: true }])
            await flush()

            expect(claimExportNudgeMessage).toHaveBeenCalledTimes(1)
            // The offer follows the export to the toast it finishes on, for anyone who did not
            // answer it while the render was running.
            expect(jest.mocked(lemonToast.updateToSuccess).mock.calls.at(-1)![1]).toEqual(
                'nudge:Export complete! +Download'
            )
        })

        it('does not claim the nudge for an export that failed', async () => {
            jest.mocked(resolveExportNudgeEligibility).mockResolvedValue({
                subject: { kind: 'dashboard', dashboardId: 9 },
                name: null,
            })
            jest.mocked(claimExportNudgeMessage).mockReturnValue(NUDGE_MESSAGE)
            jest.spyOn(api.exports, 'create').mockRejectedValue(new Error('network down'))

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 9 } })
            await flush()

            // Nothing to subscribe to yet, and claiming would spend the dashboard's one nudge.
            expect(claimExportNudgeMessage).not.toHaveBeenCalled()
            expect(lemonToast.updateToSuccess).not.toHaveBeenCalled()
        })

        it('does not claim the nudge when the completion toast is already gone', async () => {
            // Download is the expected action on that toast and dismisses it, so by the time a slow
            // check answers there may be nothing left to render into. Claiming anyway would report
            // an exposure and burn the dashboard's one nudge on a toast nobody saw.
            jest.mocked(lemonToast.isActive).mockReturnValue(false)
            jest.mocked(resolveExportNudgeEligibility).mockResolvedValue({
                subject: { kind: 'dashboard', dashboardId: 8 },
                name: null,
            })
            jest.mocked(claimExportNudgeMessage).mockReturnValue(NUDGE_MESSAGE)

            logic.actions.addFresh(asset({ id: 28, export_format: ExporterFormat.PNG, dashboard: 8 }))
            logic.actions.loadExportsSuccess([
                asset({ id: 28, export_format: ExporterFormat.PNG, has_content: true, dashboard: 8 }),
            ])
            await flush()

            expect(claimExportNudgeMessage).not.toHaveBeenCalled()
            expect(lemonToast.updateToSuccess).not.toHaveBeenCalled()
            // Without this the readout cannot tell a dropped offer from an ineligible exporter.
            expect(captureExportNudgeCheckFailed).toHaveBeenCalledWith('toast-gone', expect.anything())
        })

        it('offers a Download button when the create call outlived the user gesture', async () => {
            // A slow synchronous render outlives Safari's user-activation window, so an auto-download
            // would be silently dropped. The export must instead surface a Download button (a fresh
            // click) and stay highlighted as undownloaded until the user clicks it.
            const original = Object.getOwnPropertyDescriptor(navigator, 'userActivation')
            Object.defineProperty(navigator, 'userActivation', { value: { isActive: false }, configurable: true })
            try {
                const response = asset({ id: 15, export_format: ExporterFormat.CSV, has_content: true })
                jest.spyOn(api.exports, 'create').mockResolvedValue(response)
                const downloadExportSpy = jest.spyOn(logic.actions, 'downloadExport')

                logic.actions.createExport({ exportData: { export_format: ExporterFormat.CSV } })
                await flush()

                expect(jest.mocked(downloadExportedAsset)).not.toHaveBeenCalled()
                expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual([15])
                // A ready file is a success, so the toast settles on one and only gains the button
                // the file is claimed from. It is never dismissed, and never shows a failure.
                expect(lemonToast.dismiss).not.toHaveBeenCalled()
                expect(lemonToast.success).not.toHaveBeenCalled()
                expect(lemonToast.updateToSuccess).toHaveBeenCalledWith(
                    expect.any(String),
                    'Export complete!',
                    expect.objectContaining({ button: expect.objectContaining({ label: 'Download' }) })
                )
                jest.mocked(lemonToast.updateToSuccess).mock.calls.at(-1)![2]!.button!.action()
                expect(downloadExportSpy).toHaveBeenCalledWith(response)
            } finally {
                if (original) {
                    Object.defineProperty(navigator, 'userActivation', original)
                } else {
                    delete (navigator as any).userActivation
                }
            }
        })

        it('hands a delayed download over even when the spinner was dismissed', async () => {
            // A pending promise toast never auto-closes, so the only way it is gone is the user
            // closing it. Updating a dismissed id does nothing, which would lose the file.
            const original = Object.getOwnPropertyDescriptor(navigator, 'userActivation')
            Object.defineProperty(navigator, 'userActivation', { value: { isActive: false }, configurable: true })
            jest.mocked(lemonToast.isActive).mockReturnValue(false)
            try {
                const response = asset({ id: 61, export_format: ExporterFormat.CSV, has_content: true })
                jest.spyOn(api.exports, 'create').mockResolvedValue(response)

                logic.actions.createExport({ exportData: { export_format: ExporterFormat.CSV } })
                await flush()

                expect(jest.mocked(lemonToast.success).mock.calls).toHaveLength(1)
                expect(jest.mocked(lemonToast.success).mock.calls[0][1]?.button?.label).toEqual('Download')
            } finally {
                if (original) {
                    Object.defineProperty(navigator, 'userActivation', original)
                } else {
                    delete (navigator as any).userActivation
                }
            }
        })

        it('does not announce a delayed download twice when the list is polled again', async () => {
            // The asset waits in freshUndownloadedExports until it is clicked, so any later poll
            // sees it complete. Announcing it again would raise a second toast and, for an eligible
            // export, report a second exposure for one export.
            const original = Object.getOwnPropertyDescriptor(navigator, 'userActivation')
            Object.defineProperty(navigator, 'userActivation', { value: { isActive: false }, configurable: true })
            try {
                const response = asset({ id: 62, export_format: ExporterFormat.CSV, has_content: true })
                jest.spyOn(api.exports, 'create').mockResolvedValue(response)

                logic.actions.createExport({ exportData: { export_format: ExporterFormat.CSV } })
                await flush()
                const toastsAfterExport = jest.mocked(lemonToast.success).mock.calls.length

                logic.actions.loadExportsSuccess([response])
                await flush()

                expect(jest.mocked(lemonToast.success).mock.calls).toHaveLength(toastsAfterExport)
            } finally {
                if (original) {
                    Object.defineProperty(navigator, 'userActivation', original)
                } else {
                    delete (navigator as any).userActivation
                }
            }
        })

        it('notifies once with a Download button that routes through downloadExport', async () => {
            const pending = asset({ id: 21, export_format: ExporterFormat.MP4, has_content: false })
            const finished = asset({ id: 21, export_format: ExporterFormat.MP4, has_content: true })
            // An unrelated completed export in the list must not trigger a toast of its own.
            const unrelated = asset({ id: 99, export_format: ExporterFormat.CSV, has_content: true })
            const downloadExportSpy = jest.spyOn(logic.actions, 'downloadExport')

            logic.actions.addFresh(pending)
            logic.actions.loadExportsSuccess([finished, unrelated])
            await flush()
            // A second poll of the same finished export must not re-toast it.
            logic.actions.loadExportsSuccess([finished, unrelated])
            await flush()

            expect(jest.mocked(lemonToast.success).mock.calls).toEqual([
                [
                    'Export complete!',
                    expect.objectContaining({ button: expect.objectContaining({ label: 'Download' }) }),
                ],
            ])
            // An insight export has nothing to subscribe to, so it never asks for a nudge.
            expect(resolveExportNudgeEligibility).not.toHaveBeenCalled()
            // The export keeps its "not downloaded" highlight until the user actually downloads it.
            expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual([21])

            jest.mocked(lemonToast.success).mock.calls[0][1]!.button!.action()
            expect(downloadExportSpy).toHaveBeenCalledWith(finished)
        })

        it('uses a registered status fetcher for exports created outside the generic endpoint', async () => {
            const pending = asset({ id: 23, export_format: ExporterFormat.JSONL })
            const finished = asset({ id: 23, export_format: ExporterFormat.JSONL, has_content: true })
            const fetchLatest = jest.fn().mockResolvedValue(finished)

            logic.actions.trackExport(pending, fetchLatest)
            logic.actions.loadExportsSuccess([])
            await flush()

            expect(fetchLatest).toHaveBeenCalledTimes(1)
            expect(lemonToast.success).toHaveBeenCalledWith(
                'Export complete!',
                expect.objectContaining({ button: expect.objectContaining({ label: 'Download' }) })
            )
        })

        it('downloadExport triggers the download, clears the highlight, and confirms', async () => {
            const tracked = asset({ id: 41, export_format: ExporterFormat.MP4, has_content: true })
            logic.actions.addFresh(tracked)

            logic.actions.downloadExport(tracked)
            await flush()

            expect(jest.mocked(downloadExportedAsset).mock.calls).toEqual([[tracked]])
            expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual([])
            expect(lemonToast.success).toHaveBeenCalledWith('Download started')
        })

        it('surfaces the failure and stops tracking when a tracked async export fails', async () => {
            const pending = asset({ id: 22, export_format: ExporterFormat.MP4, has_content: false })
            const failed = asset({ id: 22, export_format: ExporterFormat.MP4, exception: 'render crashed' })

            logic.actions.addFresh(pending)
            logic.actions.loadExportsSuccess([failed])
            await flush()

            expect(lemonToast.error).toHaveBeenCalledWith('Export failed: render crashed')
            expect(logic.values.freshUndownloadedExports).toEqual([])
        })

        it('keeps polling a tracked export when its individual fetch fails', async () => {
            // A tracked export can be missing from a format-filtered list, so it is fetched directly.
            // A transient fetch failure must not stop the poll loop and orphan the export.
            jest.useFakeTimers()
            try {
                const pending = asset({ id: 31, export_format: ExporterFormat.MP4, has_content: false })
                // The list omits id 31 and its only entry is already complete, so a re-poll can
                // only come from the failed export being kept in the pending set.
                const unrelatedDone = asset({ id: 88, export_format: ExporterFormat.CSV, has_content: true })
                jest.spyOn(api.exports, 'get').mockRejectedValue(new Error('transient'))
                const loadExportsSpy = jest.spyOn(logic.actions, 'loadExports')

                logic.actions.addFresh(pending)
                logic.actions.loadExportsSuccess([unrelatedDone])
                await jest.advanceTimersByTimeAsync(30000)

                expect(api.exports.get).toHaveBeenCalledWith(31)
                expect(loadExportsSpy).toHaveBeenCalled()
                // The export is neither dropped nor prematurely notified as complete/failed.
                expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toContain(31)
                expect(lemonToast.success).not.toHaveBeenCalled()
                expect(lemonToast.error).not.toHaveBeenCalled()
            } finally {
                jest.useRealTimers()
            }
        })

        it('replaces the failure toast with the upsell survey when the export limit is reached', async () => {
            jest.spyOn(api.exports, 'create').mockRejectedValue({
                data: { attr: 'export_limit_exceeded', detail: 'You hit the cap' },
            })

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.MP4 } })
            await flush()

            expect(logic.values.hasReachedExportFullVideoLimit).toBe(true)
            expect(lemonToast.dismiss).toHaveBeenCalled()
            expect(lemonToast.error).toHaveBeenCalledWith(
                'You hit the cap',
                expect.objectContaining({ button: expect.objectContaining({ label: 'I want more' }) })
            )
            expect(jest.mocked(downloadExportedAsset).mock.calls).toEqual([])
        })
    })
})
