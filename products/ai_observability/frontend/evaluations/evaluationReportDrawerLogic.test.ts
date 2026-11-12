import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { evaluationReportDrawerLogic } from './evaluationReportDrawerLogic'
import { evaluationReportLogic } from './evaluationReportLogic'
import type { EvaluationReport, EvaluationReportRun } from './types'

const EVALUATION_ID = 'eval-1'
const REPORT: EvaluationReport = {
    id: 'report-1',
    evaluation: EVALUATION_ID,
    frequency: 'every_n',
    rrule: '',
    starts_at: null,
    timezone_name: 'UTC',
    next_delivery_date: null,
    delivery_targets: [{ type: 'email', value: 'team@example.com' }],
    max_sample_size: 200,
    enabled: true,
    deleted: false,
    last_delivered_at: null,
    report_prompt_guidance: 'Keep it short.',
    trigger_threshold: 100,
    cooldown_minutes: 1440,
    daily_run_cap: 10,
    created_by: null,
    created_at: '2026-11-01T00:00:00Z',
}

function run(id: string, createdAt: string): EvaluationReportRun {
    return {
        id,
        report: REPORT.id,
        content: { title: id, sections: [], citations: [], metrics: null, generation_status: 'completed' },
        metadata: null,
        period_start: createdAt,
        period_end: createdAt,
        delivery_status: 'delivered',
        delivery_errors: [],
        delivery_destinations: [],
        created_at: createdAt,
    }
}

// Newest first, as the runs endpoint returns them.
const FIRST_PAGE = [run('run-3', '2026-11-10T00:00:00Z'), run('run-2', '2026-11-09T00:00:00Z')]
const SECOND_PAGE = [run('run-1', '2026-11-08T00:00:00Z')]

describe('evaluationReportDrawerLogic', () => {
    let runsPages: Record<string, { results: EvaluationReportRun[]; next: string | null }>
    let patchBodies: Record<string, unknown>[]

    beforeEach(() => {
        runsPages = {
            '0': { results: FIRST_PAGE, next: 'more' },
            '2': { results: SECOND_PAGE, next: null },
        }
        patchBodies = []
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/evaluation_reports/': { results: [REPORT] },
                '/api/projects/:teamId/llm_analytics/evaluation_reports/:id/runs/': ({ request }) => {
                    const page = runsPages[new URL(request.url).searchParams.get('offset') ?? '0']
                    return page ? [200, page] : [500, {}]
                },
            },
            patch: {
                '/api/projects/:teamId/llm_analytics/evaluation_reports/:id/': async ({ request }) => {
                    patchBodies.push((await request.json()) as Record<string, unknown>)
                    return [200, REPORT]
                },
            },
            post: {
                '/api/projects/:teamId/llm_analytics/evaluation_reports/:id/generate/': [202, {}],
            },
        })
        initKeaTests()
        router.actions.push(`/project/997/ai-evals/evaluations/${EVALUATION_ID}`)
    })

    async function mountWithRuns(): Promise<ReturnType<typeof evaluationReportDrawerLogic.build>> {
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })
        reportLogic.mount()
        const logic = evaluationReportDrawerLogic({ evaluationId: EVALUATION_ID })
        logic.mount()
        await expectLogic(reportLogic).toDispatchActions(['loadReportsSuccess', 'loadReportRunsSuccess'])
        return logic
    }

    it('steps through the list in its order, with previous as the newer report', async () => {
        const logic = await mountWithRuns()

        logic.actions.openRun('run-2', 'reports_tab')

        expect(router.values.searchParams.report_run).toBe('run-2')
        expect(logic.values.previousRun?.id).toBe('run-3')
        expect(logic.values.position).toEqual({ index: 1, total: 2 })

        logic.actions.stepTo('previous')
        expect(router.values.searchParams.report_run).toBe('run-3')
        expect(logic.values.previousRun).toBeNull()
    })

    it('pages back for a linked report past the first page', async () => {
        router.actions.push(`/project/997/ai-evals/evaluations/${EVALUATION_ID}`, { report_run: 'run-1' })
        const logic = await mountWithRuns()

        await expectLogic(logic).toDispatchActions(['loadOlderReportRunsSuccess'])

        expect(logic.values.openRun?.id).toBe('run-1')
        expect(logic.values.isSearchingForRun).toBe(false)
    })

    it('stops searching for a linked report that no page has', async () => {
        router.actions.push(`/project/997/ai-evals/evaluations/${EVALUATION_ID}`, { report_run: 'deleted-run' })
        const logic = await mountWithRuns()

        await expectLogic(logic).toDispatchActions(['loadOlderReportRunsSuccess'])

        expect(logic.values.openRun).toBeNull()
        expect(logic.values.isSearchingForRun).toBe(false)
    })

    it('saves only the destinations, leaving other draft settings unsent', async () => {
        await mountWithRuns()
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })

        reportLogic.actions.setDraftReportPromptGuidance('Unsaved guidance')
        reportLogic.actions.setDraftEmailValue('alerts@example.com')
        reportLogic.actions.saveDestinations()
        await expectLogic(reportLogic).toDispatchActions(['saveReportDestinationsSuccess'])

        expect(patchBodies).toEqual([{ delivery_targets: [{ type: 'email', value: 'alerts@example.com' }] }])
        expect(reportLogic.values.configDraft.reportPromptGuidance).toBe('Unsaved guidance')
    })

    it('pauses a linked report search at the cap and resumes on request', async () => {
        const older = Array.from({ length: 120 }, (_, index) =>
            run(`old-${index}`, new Date(Date.UTC(2026, 9, 1) - index * 3_600_000).toISOString())
        )
        runsPages = { '0': { results: FIRST_PAGE, next: 'more' } }
        for (let offset = 2; offset < 122; offset += 20) {
            runsPages[String(offset)] = { results: older.slice(offset - 2, offset + 18), next: 'more' }
        }
        router.actions.push(`/project/997/ai-evals/evaluations/${EVALUATION_ID}`, { report_run: 'old-110' })
        const logic = await mountWithRuns()

        await expectLogic(logic, () => {}).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ searchPaused: true, isSearchingForRun: false })
        expect(logic.values.reportRuns.length).toBe(102)

        logic.actions.searchOlder()
        await expectLogic(logic).toDispatchActions(['loadOlderReportRunsSuccess'])
        await expectLogic(logic, () => {}).toFinishAllListeners()
        expect(logic.values.openRun?.id).toBe('old-110')
    })

    it('cancelling the destinations editor brings back the saved destinations', async () => {
        await mountWithRuns()
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })

        reportLogic.actions.setEditingDestinations(true)
        reportLogic.actions.removeDraftDestination('email')
        expect(reportLogic.values.shownDestinations).toEqual([])

        reportLogic.actions.resetDestinationsDraft(REPORT)
        expect(reportLogic.values.shownDestinations).toEqual(['email'])
        expect(reportLogic.values.configDraft.emailValue).toBe('team@example.com')
        expect(reportLogic.values.editingDestinations).toBe(false)
    })

    it('refuses to save a Slack destination without a channel', async () => {
        await mountWithRuns()
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })

        reportLogic.actions.addDraftDestination('slack')
        reportLogic.actions.setDraftSlackIntegrationId(7)
        expect(reportLogic.values.destinationsError).toBe('Pick a Slack channel, or remove Slack.')

        reportLogic.actions.saveDraft()
        await expectLogic(reportLogic).toNotHaveDispatchedActions(['updateReport'])
        expect(patchBodies).toEqual([])
    })

    it('fetches once more and stops when the report never arrives', async () => {
        await mountWithRuns()
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })
        jest.useFakeTimers()
        try {
            reportLogic.actions.generateReport(REPORT.id)
            await expectLogic(reportLogic).toDispatchActions(['generateReportSuccess'])

            jest.advanceTimersByTime(30 * 60_000 + 15_000)
            jest.useRealTimers()
            await expectLogic(reportLogic).toDispatchActions(['loadNewestReportRuns', 'stopWaitingForNewReport'])
            expect(reportLogic.values.waitingForNewReportSince).toBeNull()
        } finally {
            jest.useRealTimers()
        }
    })

    it('stops polling for good when a hidden tab returns after the deadline', async () => {
        await mountWithRuns()
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })
        const setHidden = (hidden: boolean): void => {
            Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
            document.dispatchEvent(new Event('visibilitychange'))
        }
        jest.useFakeTimers()
        try {
            reportLogic.actions.generateReport(REPORT.id)
            await expectLogic(reportLogic).toDispatchActions(['generateReportSuccess'])
            setHidden(true)
            jest.advanceTimersByTime(31 * 60_000)
            setHidden(false)
            jest.advanceTimersByTime(0)
            await expectLogic(reportLogic).toDispatchActions(['loadNewestReportRuns', 'stopWaitingForNewReport'])
            expect(reportLogic.values.waitingForNewReportSince).toBeNull()

            jest.advanceTimersByTime(60_000)
            await expectLogic(reportLogic).toNotHaveDispatchedActions(['loadNewestReportRuns'])
        } finally {
            setHidden(false)
            jest.useRealTimers()
        }
    })

    it('holds "Generate now" until the report history has loaded', async () => {
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })
        reportLogic.mount()
        await expectLogic(reportLogic).toDispatchActions(['loadReportsSuccess', 'loadReportRuns'])
        expect(reportLogic.values.reportHistoryReady).toBe(false)

        await expectLogic(reportLogic).toDispatchActions(['loadReportRunsSuccess'])
        expect(reportLogic.values.reportHistoryReady).toBe(true)
    })

    it('offers a retry when a page of a linked report fails to load', async () => {
        delete runsPages['2']
        router.actions.push(`/project/997/ai-evals/evaluations/${EVALUATION_ID}`, { report_run: 'run-1' })
        const logic = await mountWithRuns()

        await expectLogic(evaluationReportLogic({ evaluationId: EVALUATION_ID })).toDispatchActions([
            'loadOlderReportRunsFailure',
        ])
        expect(logic.values.runLoadFailed).toBe(true)
        expect(logic.values.isSearchingForRun).toBe(false)

        runsPages['2'] = { results: SECOND_PAGE, next: null }
        logic.actions.retryLoad()
        await expectLogic(logic).toDispatchActions(['loadOlderReportRunsSuccess'])
        expect(logic.values.openRun?.id).toBe('run-1')
    })

    it('waits for the new report to be delivered after "Generate now" and keeps older pages', async () => {
        await mountWithRuns()
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })
        reportLogic.actions.loadOlderReportRuns()
        await expectLogic(reportLogic).toDispatchActions(['loadOlderReportRunsSuccess'])
        jest.useFakeTimers()
        try {
            reportLogic.actions.generateReport(REPORT.id)
            await expectLogic(reportLogic).toDispatchActions(['generateReportSuccess'])
            expect(reportLogic.values.waitingForNewReportSince).not.toBeNull()

            const newRun = run('run-4', '2026-11-11T00:01:00Z')
            runsPages['0'] = { results: [{ ...newRun, delivery_status: 'pending' }, ...FIRST_PAGE], next: 'more' }
            jest.advanceTimersByTime(15_000)
            // The poll has fired. The mocked response resolves on real timers.
            jest.useRealTimers()
            await expectLogic(reportLogic).toDispatchActions(['loadNewestReportRunsSuccess'])
            expect(reportLogic.values.waitingForNewReportSince).not.toBeNull()

            // The next poll, run by hand because the interval lives on the fake clock released above.
            runsPages['0'] = { results: [newRun, ...FIRST_PAGE], next: 'more' }
            reportLogic.actions.loadNewestReportRuns(REPORT.id)
            await expectLogic(reportLogic).toDispatchActions(['loadNewestReportRunsSuccess', 'stopWaitingForNewReport'])

            expect(reportLogic.values.reportRuns.map((run) => run.id)).toEqual(['run-4', 'run-3', 'run-2', 'run-1'])
            expect(reportLogic.values.reportRuns[0].delivery_status).toBe('delivered')
        } finally {
            jest.useRealTimers()
        }
    })
})
