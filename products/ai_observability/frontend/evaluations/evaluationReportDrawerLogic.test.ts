import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { evaluationReportDrawerLogic } from './evaluationReportDrawerLogic'
import { evaluationReportLogic } from './evaluationReportLogic'
import { evaluationReportRunsLogic } from './evaluationReportRunsLogic'
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
    let reportsFail: boolean

    beforeEach(() => {
        runsPages = {
            '0': { results: FIRST_PAGE, next: 'more' },
            '2': { results: SECOND_PAGE, next: null },
        }
        patchBodies = []
        reportsFail = false
        useMocks({
            get: {
                '/api/projects/:teamId/llm_analytics/evaluation_reports/': () =>
                    reportsFail ? [500, {}] : [200, { results: [REPORT] }],
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
                '/api/projects/:teamId/llm_analytics/evaluation_reports/:id/generate/': [
                    202,
                    { requested_at: '2026-11-10T12:00:00+00:00' },
                ],
            },
        })
        initKeaTests()
        router.actions.push(`/project/997/ai-evals/evaluations/${EVALUATION_ID}`)
    })

    async function mountWithRuns(): Promise<ReturnType<typeof evaluationReportDrawerLogic.build>> {
        const runsLogic = evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })
        runsLogic.mount()
        const logic = evaluationReportDrawerLogic({ evaluationId: EVALUATION_ID })
        logic.mount()
        await expectLogic(runsLogic).toDispatchActions(['loadReportsSuccess', 'loadReportRunsSuccess'])
        return logic
    }

    it('steps through the list in its order, with previous as the newer report', async () => {
        const logic = await mountWithRuns()

        logic.actions.openRun('run-2', 'reports_tab')

        expect(router.values.searchParams.report_run).toBe('run-2')
        expect(logic.values.previousRun?.id).toBe('run-3')
        expect(logic.values.position).toEqual({ index: 1, total: 2, more: true })

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

    it('blocks the evaluation save on a Slack destination without a channel', async () => {
        await mountWithRuns()
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })

        reportLogic.actions.addDraftDestination('slack')
        reportLogic.actions.setDraftSlackIntegrationId(7)
        // The evaluation's "Save changes" refuses to write while configError is set.
        expect(reportLogic.values.configError).toBe('Pick a Slack channel, or remove Slack.')

        reportLogic.actions.setDraftSlackChannelValue('C0001|#evals')
        expect(reportLogic.values.configError).toBeNull()
    })

    it('fetches once more and stops when the report never arrives', async () => {
        await mountWithRuns()
        const runsLogic = evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })
        jest.useFakeTimers()
        try {
            runsLogic.actions.generateReport(REPORT.id)
            await expectLogic(runsLogic).toDispatchActions(['generateReportSuccess'])

            jest.advanceTimersByTime(30 * 60_000 + 15_000)
            jest.useRealTimers()
            await expectLogic(runsLogic).toDispatchActions(['loadNewestReportRunsSuccess', 'stopWaitingForNewReport'])
            expect(runsLogic.values.waitingForNewReportSince).toBeNull()
        } finally {
            jest.useRealTimers()
        }
    })

    it('stops polling for good when a hidden tab returns after the deadline', async () => {
        await mountWithRuns()
        const runsLogic = evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })
        const setHidden = (hidden: boolean): void => {
            Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
            document.dispatchEvent(new Event('visibilitychange'))
        }
        jest.useFakeTimers()
        try {
            runsLogic.actions.generateReport(REPORT.id)
            await expectLogic(runsLogic).toDispatchActions(['generateReportSuccess'])
            setHidden(true)
            jest.advanceTimersByTime(31 * 60_000)
            setHidden(false)
            jest.advanceTimersByTime(0)
            // The last fetch runs to completion before the wait ends.
            jest.useRealTimers()
            await expectLogic(runsLogic).toDispatchActions(['loadNewestReportRunsSuccess', 'stopWaitingForNewReport'])
            expect(runsLogic.values.waitingForNewReportSince).toBeNull()

            jest.useFakeTimers()
            jest.advanceTimersByTime(60_000)
            jest.useRealTimers()
            await expectLogic(runsLogic).toNotHaveDispatchedActions(['loadNewestReportRuns'])
        } finally {
            setHidden(false)
            jest.useRealTimers()
        }
    })

    it('waits from the server request time, not the loaded list, so an older report never ends the wait', async () => {
        const runsLogic = evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })
        runsLogic.mount()
        // Pressed before the history loads, so the list is still empty.
        runsLogic.actions.generateReport(REPORT.id)
        await expectLogic(runsLogic).toDispatchActions(['generateReportSuccess', 'loadNewestReportRunsSuccess'])

        expect(runsLogic.values.reportRuns.map((r) => r.id)).toContain('run-3')
        expect(runsLogic.values.waitingForNewReportSince).toBe('2026-11-10T12:00:00+00:00')
        runsLogic.actions.stopWaitingForNewReport()
    })

    it('keeps paging older when a page returns only reports already loaded', async () => {
        await mountWithRuns()
        const runsLogic = evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })
        // Two reports landed on the server, so the page after the first one repeats what is loaded.
        runsPages['2'] = { results: FIRST_PAGE, next: 'more' }
        runsPages['4'] = { results: SECOND_PAGE, next: null }

        runsLogic.actions.loadOlderReportRuns()
        await expectLogic(runsLogic).toDispatchActions(['loadOlderReportRunsSuccess'])
        runsLogic.actions.loadOlderReportRuns()
        await expectLogic(runsLogic).toDispatchActions(['loadOlderReportRunsSuccess'])

        expect(runsLogic.values.reportRuns.map((r) => r.id)).toEqual(['run-3', 'run-2', 'run-1'])
    })

    it('does not skip the oldest report when a new one arrives between paging and polling', async () => {
        await mountWithRuns()
        const runsLogic = evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })
        const newest = run('run-4', '2026-11-11T00:00:00Z')
        const oldest = run('run-0', '2026-11-07T00:00:00Z')
        // run-4 lands before anyone polls: the server list is now run-4, run-3, run-2, run-1, run-0.
        runsPages['2'] = { results: [run('run-2', '2026-11-09T00:00:00Z'), SECOND_PAGE[0]], next: 'more' }
        runsPages['4'] = { results: [oldest], next: null }
        runsPages['0'] = { results: [newest, ...FIRST_PAGE], next: 'more' }

        runsLogic.actions.loadOlderReportRuns()
        await expectLogic(runsLogic).toDispatchActions(['loadOlderReportRunsSuccess'])
        runsLogic.actions.loadNewestReportRuns(REPORT.id)
        await expectLogic(runsLogic).toDispatchActions(['loadNewestReportRunsSuccess'])
        runsLogic.actions.loadOlderReportRuns()
        await expectLogic(runsLogic).toDispatchActions(['loadOlderReportRunsSuccess'])

        expect(runsLogic.values.reportRuns.map((r) => r.id)).toEqual(['run-4', 'run-3', 'run-2', 'run-1', 'run-0'])
    })

    it('steps older past the loaded page by loading the next one', async () => {
        const logic = await mountWithRuns()
        logic.actions.openRun('run-2', 'reports_tab')
        expect(logic.values.nextRun).toBeNull()
        expect(logic.values.canStepOlder).toBe(true)

        logic.actions.stepTo('next')
        await expectLogic(logic).toDispatchActions(['loadOlderReportRunsSuccess'])

        expect(router.values.searchParams.report_run).toBe('run-1')
        expect(logic.values.canStepOlder).toBe(false)
    })

    it('retries a failed reports load for a linked report instead of calling it deleted', async () => {
        reportsFail = true
        router.actions.push(`/project/997/ai-evals/evaluations/${EVALUATION_ID}`, { report_run: 'run-1' })
        const reportLogic = evaluationReportLogic({ evaluationId: EVALUATION_ID })
        const logic = evaluationReportDrawerLogic({ evaluationId: EVALUATION_ID })
        logic.mount()
        await expectLogic(reportLogic).toDispatchActions(['loadReportsFailure'])
        expect(logic.values.runLoadFailed).toBe(true)

        reportsFail = false
        logic.actions.retryLoad()
        await expectLogic(reportLogic).toDispatchActions(['loadReportsSuccess'])
        await expectLogic(evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })).toDispatchActions([
            'loadOlderReportRunsSuccess',
        ])
        expect(logic.values.openRun?.id).toBe('run-1')
    })

    it('offers a retry when a page of a linked report fails to load', async () => {
        delete runsPages['2']
        router.actions.push(`/project/997/ai-evals/evaluations/${EVALUATION_ID}`, { report_run: 'run-1' })
        const logic = await mountWithRuns()

        await expectLogic(evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })).toDispatchActions([
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
        const runsLogic = evaluationReportRunsLogic({ evaluationId: EVALUATION_ID })
        runsLogic.actions.loadOlderReportRuns()
        await expectLogic(runsLogic).toDispatchActions(['loadOlderReportRunsSuccess'])
        jest.useFakeTimers()
        try {
            runsLogic.actions.generateReport(REPORT.id)
            await expectLogic(runsLogic).toDispatchActions(['generateReportSuccess'])
            expect(runsLogic.values.waitingForNewReportSince).not.toBeNull()

            const newRun = run('run-4', '2026-11-11T00:01:00Z')
            // A pending or failed delivery can still change, so neither ends the wait.
            runsPages['0'] = { results: [{ ...newRun, delivery_status: 'failed' }, ...FIRST_PAGE], next: 'more' }
            jest.advanceTimersByTime(15_000)
            // The poll has fired. The mocked response resolves on real timers.
            jest.useRealTimers()
            await expectLogic(runsLogic).toDispatchActions(['loadNewestReportRunsSuccess'])
            expect(runsLogic.values.waitingForNewReportSince).not.toBeNull()

            // The next poll, run by hand because the interval lives on the fake clock released above.
            runsPages['0'] = { results: [newRun, ...FIRST_PAGE], next: 'more' }
            runsLogic.actions.loadNewestReportRuns(REPORT.id)
            await expectLogic(runsLogic).toDispatchActions(['loadNewestReportRunsSuccess', 'stopWaitingForNewReport'])

            expect(runsLogic.values.reportRuns.map((run) => run.id)).toEqual(['run-4', 'run-3', 'run-2', 'run-1'])
            expect(runsLogic.values.reportRuns[0].delivery_status).toBe('delivered')
        } finally {
            jest.useRealTimers()
        }
    })
})
