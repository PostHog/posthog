import { act, cleanup, render, screen } from '@testing-library/react'
import { ToastContainer, toast } from 'react-toastify'

import api from 'lib/api'
import { resolveExportNudgeEligibility } from 'scenes/dashboard/dashboardExportNudgeLogic'
import { exportCompleteNudgeMessage } from 'scenes/dashboard/DashboardExportNudgeToast'

import { initKeaTests } from '~/test/init'
import { ExportedAssetType, ExporterFormat } from '~/types'

import { exportsLogic } from './exportsLogic'

jest.mock('./exporter', () => ({
    ...jest.requireActual('./exporter'),
    downloadExportedAsset: jest.fn(),
}))
jest.mock('scenes/dashboard/dashboardExportNudgeLogic', () => ({
    resolveExportNudgeEligibility: jest.fn(async () => null),
    // The real logic sits in an import cycle with exportsLogic, so resolve it on access rather than
    // while this factory runs, when it is still undefined.
    get dashboardExportNudgeLogic() {
        return jest.requireActual('scenes/dashboard/dashboardExportNudgeLogic').dashboardExportNudgeLogic
    },
}))
jest.mock('scenes/dashboard/DashboardExportNudgeToast', () => ({
    exportCompleteNudgeMessage: jest.fn(),
}))

const NUDGE_CTA = 'Set up recurring updates'

// Long enough to clear the nudge deadline and both of react-toastify's 100ms update delays, while
// staying inside the 5s a success toast is left on screen for.
const SETTLE_MS = 6000

// react-toastify and lemonToast are deliberately left unmocked: this suite exists because the
// completion toast's final rendered state is the only place the regression below is visible.
describe('export completion toast', () => {
    let logic: ReturnType<typeof exportsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(exportCompleteNudgeMessage).mockImplementation((candidate) =>
            candidate ? <span>{NUDGE_CTA}</span> : null
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

    it.each([
        {
            label: 'shows the nudge once the export lands, not the spinner it started with',
            eligibility: (): Promise<any> => Promise.resolve({ dashboardId: 7, dashboardName: 'Weekly' }),
            expected: NUDGE_CTA,
        },
        {
            label: 'falls back to the plain message when the nudge check never resolves',
            eligibility: (): Promise<any> => new Promise(() => {}),
            expected: 'Export complete!',
        },
    ])('$label', async ({ eligibility, expected }) => {
        jest.mocked(resolveExportNudgeEligibility).mockReturnValue(eligibility())

        render(<ToastContainer />)
        logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG, dashboard: 7 } })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(SETTLE_MS)
        })

        expect(screen.getByText(expected)).toBeTruthy()
        // The export finished, so leaving its spinner up strands the user on "Preparing export…".
        expect(screen.queryByText('Preparing export…')).toBeNull()
    })
})
