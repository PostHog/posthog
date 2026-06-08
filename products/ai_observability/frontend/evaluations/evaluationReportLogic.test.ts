import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { evaluationReportLogic } from './evaluationReportLogic'
import { EvaluationReport } from './types'

const makeReport = (overrides: Partial<EvaluationReport> = {}): EvaluationReport => ({
    id: 'report-1',
    evaluation: 'eval-1',
    frequency: 'every_n',
    rrule: '',
    starts_at: null,
    timezone_name: 'UTC',
    next_delivery_date: null,
    delivery_targets: [{ type: 'email', value: 'team@example.com' }],
    max_sample_size: 100,
    enabled: true,
    deleted: false,
    last_delivered_at: null,
    report_prompt_guidance: '',
    trigger_threshold: 100,
    cooldown_minutes: 60,
    daily_run_cap: 10,
    created_by: null,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
})

describe('evaluationReportLogic', () => {
    let logic: ReturnType<typeof evaluationReportLogic.build>
    // The mock handlers read these lazily at request time, so each test sets
    // `reports` before triggering loadReports. `patchBodies` records every PATCH
    // body to an evaluation_reports detail route, in call order.
    let reports: EvaluationReport[]
    let patchBodies: Record<string, unknown>[]

    beforeEach(() => {
        reports = []
        patchBodies = []
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/evaluation_reports/': () => [200, { results: reports }],
                '/api/environments/:teamId/llm_analytics/evaluation_reports/:id/runs/': { results: [] },
            },
            patch: {
                '/api/environments/:teamId/llm_analytics/evaluation_reports/:id/': async (req) => {
                    const body = (await req.json()) as Record<string, unknown>
                    patchBodies.push(body)
                    const id = req.params.id as string
                    const current = reports.find((r) => r.id === id) ?? makeReport({ id })
                    return [200, { ...current, ...body }]
                },
            },
        })

        initKeaTests()
        logic = evaluationReportLogic({ evaluationId: 'eval-1' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('seeds the draft from the report enabled state rather than forcing true', async () => {
        reports = [makeReport({ enabled: false })]
        logic.actions.loadReports()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.configDraft.enabled).toBe(false)
    })

    it('treats a paused (enabled=false) report as the active report', async () => {
        reports = [makeReport({ enabled: false })]
        logic.actions.loadReports()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeReport).toEqual(expect.objectContaining({ id: 'report-1', enabled: false }))
    })

    it.each([
        { label: 'disabling persists enabled:false without soft-deleting', initialEnabled: true, target: false },
        { label: 're-enables a paused report', initialEnabled: false, target: true },
    ])('$label', async ({ initialEnabled, target }) => {
        reports = [makeReport({ enabled: initialEnabled })]
        logic.actions.loadReports()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setReportsEnabled(target)
        await expectLogic(logic).toFinishAllListeners()

        // Only `enabled` is PATCHed — never `deleted` — so the config is preserved either way.
        expect(patchBodies).toEqual([{ enabled: target }])
        expect(logic.values.activeReport).toEqual(expect.objectContaining({ enabled: target }))
    })

    it('disables every non-deleted report so duplicates cannot keep delivering', async () => {
        reports = [
            makeReport({ id: 'report-1', enabled: true }),
            makeReport({ id: 'report-2', enabled: true }),
            makeReport({ id: 'report-deleted', enabled: true, deleted: true }),
        ]
        logic.actions.loadReports()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setReportsEnabled(false)
        await expectLogic(logic).toFinishAllListeners()

        // Two PATCHes — one per non-deleted report; the soft-deleted one is left alone.
        expect(patchBodies).toEqual([{ enabled: false }, { enabled: false }])
        expect(logic.values.reports.filter((r) => !r.deleted).every((r) => !r.enabled)).toBe(true)
    })

    it('re-enables only the visible report so historical duplicates stay paused', async () => {
        reports = [makeReport({ id: 'report-1', enabled: false }), makeReport({ id: 'report-2', enabled: false })]
        logic.actions.loadReports()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setReportsEnabled(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(patchBodies).toEqual([{ enabled: true }])
        expect(logic.values.reports).toEqual([
            expect.objectContaining({ id: 'report-1', enabled: true }),
            expect.objectContaining({ id: 'report-2', enabled: false }),
        ])
    })
})
