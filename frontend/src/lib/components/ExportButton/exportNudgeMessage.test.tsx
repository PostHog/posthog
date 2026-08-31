import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { toast } from 'react-toastify'

import { initKeaTests } from '~/test/init'

import { ExportNudgeCandidate } from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'
import { claimExportNudgeMessage } from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/ExportNudgeToast'

jest.mock('products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic', () => ({
    ...jest.requireActual('products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'),
    claimExportNudge: () => true,
}))

const CANDIDATE: ExportNudgeCandidate = { subject: { kind: 'dashboard', dashboardId: 7 }, name: 'Weekly numbers' }

describe('export nudge message', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('closes only the toast it belongs to when the export action is taken', () => {
        // Dismissing without an id closes every toast on screen, including another export's
        // completion toast, which for a polled export is its only signal.
        const dismiss = jest.spyOn(toast, 'dismiss').mockImplementation((() => {}) as any)
        const action = jest.fn()
        const message = claimExportNudgeMessage(CANDIDATE)

        render(<>{message!('Export complete!', 'export-toast', { label: 'Download', action })}</>)
        fireEvent.click(screen.getByText('Download'))

        expect(action).toHaveBeenCalled()
        expect(dismiss).toHaveBeenCalledWith('export-toast')
    })
})
