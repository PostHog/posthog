import { ExporterFormat } from '~/types'

import type { ExportNudgeCandidate } from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'

jest.mock('products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic', () => ({
    lookUpExportNudge: jest.fn(),
    resolveExportNudgeEligibility: jest.fn(async () => null),
    captureExportNudgeCheckFailed: jest.fn(),
    exportNudgeEventProperties: jest.fn(() => ({})),
}))
jest.mock('products/subscriptions/frontend/components/Subscriptions/exportNudge/ExportNudgeToast', () => ({
    claimExportNudgeMessage: jest.fn(),
}))

const CANDIDATE: ExportNudgeCandidate = { subject: { kind: 'dashboard', dashboardId: 7 }, name: 'Weekly' }

describe('startExportNudge before the subscriptions code loads', () => {
    it.each([
        ['an eligible dashboard export', ExporterFormat.PNG, { status: 'eligible', candidate: CANDIDATE }, CANDIDATE],
        ['an ineligible dashboard export', ExporterFormat.PNG, { status: 'ineligible' }, null],
        ['a CSV export', ExporterFormat.CSV, { status: 'eligible', candidate: CANDIDATE }, null],
    ])('folds the answer for %s into the settled toast', async (_, format, lookup, expected) => {
        await jest.isolateModulesAsync(async () => {
            const { lookUpExportNudge } =
                await import('products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic')
            jest.mocked(lookUpExportNudge).mockReturnValue(lookup as ReturnType<typeof lookUpExportNudge>)
            const { startExportNudge } = await import('./exportNudge')

            const nudge = startExportNudge({ export_format: format, dashboard: 7 })

            expect(nudge.message).toBeNull()
            await expect(nudge.resolving).resolves.toEqual(expected)
        })
    })
})
