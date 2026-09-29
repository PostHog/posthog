import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SAMPLE_REPORTS } from './todayFixtures'
import { routeFromSearchParams, todayLogic } from './todayLogic'
import { toTodayReport, summaryParagraphs } from './todaySignalReports'

const REPORT = {
    id: 'report-1',
    title: 'Signup form rejects plus-addressed emails',
    summary: 'Sign-ups fail since the [last release](chart:abc).\n\n## Impact\n\nMost **new** teams are affected.',
    status: 'ready',
    total_weight: 4,
    signal_count: 12,
    created_at: '2026-09-27T09:00:00Z',
    updated_at: '2026-09-28T07:00:00Z',
    artefact_count: 2,
    is_suggested_reviewer: true,
    source_products: ['error_tracking', 'session_replay'],
    implementation_pr_url: 'https://github.com/example/app/pull/42',
} as any

describe('todayLogic', () => {
    let signalReports: any[]

    beforeEach(() => {
        signalReports = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': () => [
                    200,
                    { results: signalReports, count: signalReports.length },
                ],
            },
        })
        initKeaTests()
    })

    test.each([
        [{}, { view: 'home', reportId: null, conversationId: null, evidenceId: null }],
        [{ report: 'pr' }, { view: 'report', reportId: 'pr', conversationId: null, evidenceId: null }],
        [
            { report: 'pr', view: 'follow-up' },
            { view: 'follow-up', reportId: 'pr', conversationId: null, evidenceId: null },
        ],
        [
            { view: 'library', type: 'feature_flag' },
            { view: 'library', reportId: null, conversationId: null, evidenceId: null },
        ],
        [
            { view: 'new', conversation: 'c1', evidence: 'e1' },
            { view: 'new', reportId: null, conversationId: 'c1', evidenceId: 'e1' },
        ],
    ])('reads the view from %o', (searchParams, route) => {
        expect(routeFromSearchParams(searchParams)).toEqual(route)
    })

    it('uses sample reports only when the project has no actionable reports', async () => {
        const logic = todayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.usingSampleReports).toBe(true)
        expect(logic.values.reports).toEqual(SAMPLE_REPORTS)
        logic.unmount()

        signalReports = [REPORT]
        const withReports = todayLogic()
        withReports.mount()
        await expectLogic(withReports).toFinishAllListeners()
        expect(withReports.values.usingSampleReports).toBe(false)
        expect(withReports.values.reports.map((report) => report.id)).toEqual(['report-report-1'])
    })

    it('walks a primary action through its steps and marks the report done', async () => {
        jest.useFakeTimers()
        try {
            const logic = todayLogic()
            logic.mount()
            logic.actions.runReportAction('exp')
            expect(logic.values.actionStates.exp).toBe('loading')
            expect(logic.values.actionMessage).toBe('Turning on one-page-checkout for 10% of users…')

            jest.advanceTimersByTime(900)
            expect(logic.values.actionMessage).toBe('Guardrails holding. Rolling out to 50%…')

            jest.advanceTimersByTime(2000)
            expect(logic.values.actionStates.exp).toBe('complete')
            expect(logic.values.visibleReports.find((report) => report.id === 'exp')?.completed).toBe(true)
        } finally {
            jest.useRealTimers()
        }
    })

    it('turns a signal report into a Today report that opens its pull request', () => {
        const report = toTodayReport(REPORT, '/inbox/reports/report-1')
        expect(report).toMatchObject({
            title: 'Signup form rejects plus-addressed emails',
            icon: 'pr',
            action: { primary: 'Review the pull request', href: 'https://github.com/example/app/pull/42' },
            evidence: [{ product: 'Error tracking' }, { product: 'Session replay' }],
        })
        expect(summaryParagraphs(REPORT.summary)).toEqual([
            'Sign-ups fail since the last release.',
            'Impact',
            'Most new teams are affected.',
        ])
    })
})
