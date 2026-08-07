import { act, cleanup, render, screen } from '@testing-library/react'
import { ToastContainer, toast } from 'react-toastify'

import api from 'lib/api'
import { resolveExportNudgeEligibility } from 'scenes/dashboard/dashboardExportNudgeLogic'
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

    it('falls back to the plain message when the nudge check never resolves', async () => {
        jest.mocked(resolveExportNudgeEligibility).mockReturnValue(new Promise(() => {}))

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(SETTLE_MS)
        })

        expect(screen.getByText('Export complete!')).toBeTruthy()
        // The export finished, so leaving its spinner up strands the user on "Preparing export…".
        expect(screen.queryByText('Preparing export…')).toBeNull()
    })

    it('keeps one toast carrying the nudge from the wait through to completion', async () => {
        jest.mocked(resolveExportNudgeEligibility).mockResolvedValue({ dashboardId: 7, dashboardName: 'Weekly' })
        let finishExport: (asset: ExportedAssetType) => void = () => {}
        jest.mocked(api.exports.create).mockReturnValue(
            new Promise<ExportedAssetType>((resolve) => {
                finishExport = resolve
            })
        )

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(500)
        })

        // Still exporting, and the nudge is already readable rather than waiting for the export.
        expect(screen.getByText('Preparing export…')).toBeTruthy()
        expect(screen.getByText(NUDGE_CTA)).toBeTruthy()
        expectButtonRow()

        finishExport({
            id: 31,
            export_format: ExporterFormat.PNG,
            has_content: true,
            filename: 'dashboard.png',
            created_at: '2026-05-11T19:00:00Z',
            dashboard: 7,
        } as ExportedAssetType)
        await act(async () => {
            await jest.advanceTimersByTimeAsync(SETTLE_MS)
        })

        // The nudge has to survive react-toastify re-rendering from the success config.
        expect(screen.getByText(NUDGE_CTA)).toBeTruthy()
        expect(screen.queryByText('Preparing export…')).toBeNull()
        expect(screen.getAllByText(NUDGE_CTA)).toHaveLength(1)
        expectButtonRow()
    })
})
