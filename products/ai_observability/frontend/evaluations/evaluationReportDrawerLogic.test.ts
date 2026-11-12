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
                '/api/projects/:teamId/llm_analytics/evaluation_reports/:id/runs/': ({ request }) => [
                    200,
                    runsPages[new URL(request.url).searchParams.get('offset') ?? '0'],
                ],
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
        await expectLogic(reportLogic).toDispatchActions(['updateReportSuccess'])

        expect(patchBodies).toEqual([{ delivery_targets: [{ type: 'email', value: 'alerts@example.com' }] }])
    })

    it('waits for the new report after "Generate now" and stops once it arrives', async () => {
        await mountWithRuns()
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })
        jest.useFakeTimers()
        try {
            reportLogic.actions.generateReport(REPORT.id)
            await expectLogic(reportLogic).toDispatchActions(['generateReportSuccess'])
            expect(reportLogic.values.waitingForNewReportSince).not.toBeNull()

            runsPages['0'] = { results: [run('run-4', '2026-11-11T00:01:00Z'), ...FIRST_PAGE], next: 'more' }
            jest.advanceTimersByTime(15_000)
            // The poll has fired. The mocked response resolves on real timers.
            jest.useRealTimers()
            await expectLogic(reportLogic).toDispatchActions(['loadReportRunsSuccess', 'stopWaitingForNewReport'])

            expect(reportLogic.values.waitingForNewReportSince).toBeNull()
            expect(reportLogic.values.reportRuns[0].id).toBe('run-4')
        } finally {
            jest.useRealTimers()
        }
    })
})
