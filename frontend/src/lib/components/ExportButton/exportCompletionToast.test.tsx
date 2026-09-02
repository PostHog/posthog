import { act, cleanup, render, screen } from '@testing-library/react'
import { ToastContainer, toast } from 'react-toastify'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { ExportedAssetType, ExporterFormat, InsightShortId } from '~/types'

import {
    ExportNudgeCandidate,
    captureExportNudgeCheckFailed,
    lookUpExportNudge,
    resolveExportNudgeEligibility,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'
import { claimExportNudgeMessage } from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/ExportNudgeToast'

import { downloadExportedAsset } from './exporter'
import { exportsLogic } from './exportsLogic'

jest.mock('./exporter', () => ({
    ...jest.requireActual('./exporter'),
    downloadExportedAsset: jest.fn(),
}))
jest.mock('products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic', () => ({
    lookUpExportNudge: jest.fn(() => ({ status: 'unknown' })),
    resolveExportNudgeEligibility: jest.fn(async () => null),
    captureExportNudgeCheckFailed: jest.fn(),
    exportNudgeEventProperties: jest.fn(() => ({})),
}))
jest.mock('products/subscriptions/frontend/components/Subscriptions/exportNudge/ExportNudgeToast', () => ({
    claimExportNudgeMessage: jest.fn(),
}))

const NUDGE_CTA = 'Subscribe'
const DASHBOARD_CANDIDATE: ExportNudgeCandidate = {
    subject: { kind: 'dashboard', dashboardId: 7 },
    name: 'Weekly',
}
const INSIGHT_CANDIDATE: ExportNudgeCandidate = {
    subject: { kind: 'insight', insightShortId: '11' as InsightShortId },
    name: null,
}

// Long enough to clear the nudge deadline and react-toastify's 100ms update delay, while staying
// inside the 5s a success toast is left on screen for.
const SETTLE_MS = 6000

describe('export completion toast', () => {
    let logic: ReturnType<typeof exportsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        // Stands in for the real offer: the headline, a CTA that retires the offer the way following
        // it does, and the export's own action, which this message owns the layout of either way.
        jest.mocked(claimExportNudgeMessage).mockImplementation(() => {
            let accepted = false
            return (headline, _toastId, action) => (
                <span>
                    <span>{headline}</span>
                    {!accepted && <button onClick={() => (accepted = true)}>{NUDGE_CTA}</button>}
                    {action && <button onClick={() => void action.action()}>{action.label}</button>}
                </span>
            )
        })
        jest.mocked(lookUpExportNudge).mockReturnValue({ status: 'unknown' })
        jest.useFakeTimers()
        initKeaTests()
        logic = exportsLogic()
        logic.mount()
        jest.spyOn(api.exports, 'list').mockResolvedValue({ results: [], count: 0 } as any)
        jest.spyOn(api.exports, 'create').mockResolvedValue({
            id: 31,
            export_format: ExporterFormat.PNG,
            has_content: true,
            filename: 'dashboard.png',
            created_at: '2026-05-11T19:00:00Z',
            dashboard: 7,
        })
    })

    afterEach(() => {
        toast.dismiss()
        cleanup()
        logic.unmount()
        jest.useRealTimers()
        // jsdom ships no userActivation, which the export reads as a live gesture. Any test that
        // pins it has to hand that default back.
        delete (window.navigator as any).userActivation
    })

    it('leaves unrelated toasts alone when View exports is clicked', async () => {
        // Only a video render offers the link, since it is the export that lands in the panel later.
        jest.mocked(api.exports.create).mockResolvedValue({
            id: 32,
            export_format: ExporterFormat.MP4,
            has_content: false,
            filename: 'recording.mp4',
            created_at: '2026-05-11T19:00:00Z',
        })

        render(<ToastContainer />)
        act(() => {
            toast.info('An unrelated notification', { toastId: 'unrelated' })
        })
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.MP4 } })
        // Settles the kickoff onto its success frame while staying inside the 5s it is left up for.
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1000)
        })
        expect(screen.getByText('Export started')).toBeTruthy()
        expect(screen.queryByText('An unrelated notification')).not.toBeNull()

        const dismiss = jest.spyOn(toast, 'dismiss')
        act(() => {
            screen.getByText('View exports').click()
            jest.advanceTimersByTime(1000)
        })

        // Without an id the button calls toast.dismiss(undefined), which clears every toast.
        expect(dismiss).toHaveBeenCalled()
        expect(dismiss.mock.calls[0][0]).not.toBeUndefined()
        expect(screen.queryByText('An unrelated notification')).not.toBeNull()
    })

    it('completes the export toast without waiting for a nudge check that stalls', async () => {
        jest.mocked(resolveExportNudgeEligibility).mockReturnValue(new Promise(() => {}))

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
        // Deliberately shorter than the check's deadline: the file has already downloaded, so
        // leaving its spinner up strands the user on "Preparing export…" for five more seconds.
        await act(async () => {
            await jest.advanceTimersByTimeAsync(500)
        })

        expect(screen.getByText('Export complete!')).toBeTruthy()
        expect(screen.queryByText('Preparing export…')).toBeNull()

        await act(async () => {
            await jest.advanceTimersByTimeAsync(SETTLE_MS)
        })

        // A stall reports its own step, otherwise the readout cannot tell it from an exporter who
        // was simply ineligible.
        expect(captureExportNudgeCheckFailed).toHaveBeenCalledWith('timeout', expect.anything())
    })

    it.each([
        ['a dashboard', { dashboard: 7 }, DASHBOARD_CANDIDATE],
        ['an insight', { insight: 11, insightShortId: '11' as InsightShortId }, INSIGHT_CANDIDATE],
    ])(
        'carries the offer from the first frame when %s export needs no check',
        async (_label, exportData, candidate) => {
            jest.mocked(lookUpExportNudge).mockReturnValue({ status: 'eligible', candidate })
            let finishExport: (asset: ExportedAssetType) => void = () => {}
            jest.mocked(api.exports.create).mockReturnValue(
                new Promise<ExportedAssetType>((resolve) => {
                    finishExport = resolve
                })
            )

            render(<ToastContainer />)
            logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, ...exportData } })
            await act(async () => {
                await jest.advanceTimersByTimeAsync(100)
            })

            // Still exporting, and the offer is already readable rather than waiting for the export.
            expect(screen.getByText('Preparing export…')).toBeTruthy()
            expect(screen.getByText(NUDGE_CTA)).toBeTruthy()

            finishExport({
                id: 31,
                export_format: ExporterFormat.PNG,
                has_content: true,
                filename: 'export.png',
                created_at: '2026-05-11T19:00:00Z',
            })
            await act(async () => {
                await jest.advanceTimersByTimeAsync(SETTLE_MS)
            })

            // One toast, settled, still carrying the offer, rather than a second one alongside it.
            expect(screen.queryByText('Preparing export…')).toBeNull()
            expect(screen.getAllByText(NUDGE_CTA)).toHaveLength(1)
            expect(document.querySelectorAll('.Toastify__toast')).toHaveLength(1)
            expect(resolveExportNudgeEligibility).not.toHaveBeenCalled()
        }
    )

    it('folds a late offer into the toast the export settled into', async () => {
        jest.mocked(resolveExportNudgeEligibility).mockResolvedValue(DASHBOARD_CANDIDATE)

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(SETTLE_MS)
        })

        // The rewrite has to replace the settled frame react-toastify rendered from the success
        // config, not sit alongside it.
        expect(screen.getByText('Export complete!')).toBeTruthy()
        expect(screen.getAllByText(NUDGE_CTA)).toHaveLength(1)
        expect(document.querySelectorAll('.Toastify__toast')).toHaveLength(1)
    })

    it('never shows a failure while handing over a finished file', async () => {
        // The file is ready; it just needs a fresh click to download. Routing that through a
        // rejection paints the toast red with the internal reason on the way past.
        Object.defineProperty(window.navigator, 'userActivation', { value: { isActive: false }, configurable: true })
        jest.mocked(api.exports.create).mockResolvedValue({
            id: 51,
            export_format: ExporterFormat.PNG,
            has_content: true,
            filename: 'insight.png',
            created_at: '2026-05-11T19:00:00Z',
        })

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG } })

        // Sampled across the settle, not just at the end: the red frame is transient.
        const seen: string[] = []
        for (let tick = 0; tick < 12; tick++) {
            await act(async () => {
                await jest.advanceTimersByTimeAsync(50)
            })
            seen.push(document.body.innerHTML)
        }

        expect(seen.some((html) => html.includes('Toastify__toast--error'))).toBe(false)
        expect(seen.some((html) => html.includes('Export awaiting user download'))).toBe(false)
        expect(screen.getByText('Export complete!')).toBeTruthy()
        expect(screen.getByText('Download')).toBeTruthy()
    })

    it('leaves the finished download reachable when the offer is followed mid-export', async () => {
        // A render that outlives the click's activation hands the file over on a Download button
        // instead of downloading it outright, which is the case the CTA could strand.
        Object.defineProperty(window.navigator, 'userActivation', {
            value: { isActive: false },
            configurable: true,
        })
        jest.mocked(lookUpExportNudge).mockReturnValue({ status: 'eligible', candidate: DASHBOARD_CANDIDATE })
        let finishExport: (asset: ExportedAssetType) => void = () => {}
        jest.mocked(api.exports.create).mockReturnValue(
            new Promise<ExportedAssetType>((resolve) => {
                finishExport = resolve
            })
        )

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(100)
        })

        act(() => {
            screen.getByText(NUDGE_CTA).click()
        })

        finishExport({
            id: 31,
            export_format: ExporterFormat.PNG,
            has_content: true,
            filename: 'dashboard.png',
            created_at: '2026-05-11T19:00:00Z',
            dashboard: 7,
        })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(SETTLE_MS)
        })
        // Dismissing on the CTA would take the button the file arrives on with it.
        expect(screen.getByText('Export complete!')).toBeTruthy()
        expect(screen.queryByText(NUDGE_CTA)).toBeNull()

        act(() => {
            screen.getByText('Download').click()
        })
        expect(downloadExportedAsset).toHaveBeenCalled()
    })
})
