import { act, cleanup, render, screen } from '@testing-library/react'
import { ToastContainer, toast } from 'react-toastify'

import api from 'lib/api'
import {
    captureExportNudgeCheckFailed,
    resolveExportNudgeEligibility,
} from 'scenes/dashboard/dashboardExportNudgeLogic'
import { claimExportNudgeMessage } from 'scenes/dashboard/DashboardExportNudgeToast'

import { initKeaTests } from '~/test/init'
import { ExportedAssetType, ExporterFormat } from '~/types'

import { exportsLogic } from './exportsLogic'

jest.mock('./exporter', () => ({
    ...jest.requireActual('./exporter'),
    downloadExportedAsset: jest.fn(),
}))
jest.mock('scenes/dashboard/dashboardExportNudgeLogic', () => ({
    resolveExportNudgeEligibility: jest.fn(async () => null),
    captureExportNudgeCheckFailed: jest.fn(),
}))
jest.mock('scenes/dashboard/DashboardExportNudgeToast', () => ({
    claimExportNudgeMessage: jest.fn(),
}))

const NUDGE_CTA = 'Set up recurring updates'

// Long enough to clear the nudge deadline and both of react-toastify's 100ms update delays, while
// staying inside the 5s a success toast is left on screen for.
const SETTLE_MS = 6000

function expectButtonRow(): void {
    const row = document.querySelector('.nudge-button-row')
    expect(row?.textContent).toEqual(`${NUDGE_CTA}View exports`)
    expect(screen.getAllByText('View exports')).toHaveLength(1)
}

describe('export completion toast', () => {
    let logic: ReturnType<typeof exportsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(claimExportNudgeMessage).mockImplementation((candidate) =>
            candidate
                ? (headline, secondaryAction) => (
                      <span>
                          <span>{headline}</span>
                          <span className="nudge-button-row">
                              <button>{NUDGE_CTA}</button>
                              {secondaryAction && <button>{secondaryAction.label}</button>}
                          </span>
                      </span>
                  )
                : null
        )
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
        } as ExportedAssetType)
    })

    afterEach(() => {
        toast.dismiss()
        cleanup()
        logic.unmount()
        jest.useRealTimers()
    })

    it('completes the export toast without waiting for the nudge check', async () => {
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
        expect(captureExportNudgeCheckFailed).toHaveBeenCalledWith('timeout')
    })

    it('does not offer the exports panel when the export failed', async () => {
        jest.mocked(resolveExportNudgeEligibility).mockResolvedValue(null)
        jest.mocked(api.exports.create).mockRejectedValue(new Error('render crashed'))

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(SETTLE_MS)
        })

        // Nothing landed in the panel, so the link would send the user somewhere with no answer.
        expect(document.querySelector('[data-attr="error-toast"]')).toBeTruthy()
        expect(screen.queryByText('View exports')).toBeNull()
    })

    it('folds the nudge into the completed export toast rather than raising a second one', async () => {
        jest.mocked(resolveExportNudgeEligibility).mockResolvedValue({ dashboardId: 7, dashboardName: 'Weekly' })

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(SETTLE_MS)
        })

        // The rewrite has to replace the settled frame react-toastify rendered from the success
        // config, not sit alongside it.
        expect(screen.queryByText('Preparing export…')).toBeNull()
        expect(screen.getAllByText(NUDGE_CTA)).toHaveLength(1)
        expect(document.querySelectorAll('.Toastify__toast')).toHaveLength(1)
        expectButtonRow()
    })
})
