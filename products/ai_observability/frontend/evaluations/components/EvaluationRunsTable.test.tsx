import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { getEvaluationResultDisplay } from '../../components/EvaluationResultTag'
import { traceDrawerLogic } from '../../redesign/trace/traceDrawerLogic'
import { traceViewHostLogic } from '../../redesign/trace/traceViewHostLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationConfig, EvaluationRun } from '../types'
import { EvaluationRunsTable } from './EvaluationRunsTable'

const props = { evaluationId: 'eval-123' }

function renderTable(): void {
    render(
        <Provider>
            <BindLogic logic={llmEvaluationLogic} props={props}>
                <EvaluationRunsTable />
            </BindLogic>
        </Provider>
    )
}

const passingRun: EvaluationRun = {
    id: 'run-1',
    evaluation_id: 'eval-123',
    evaluation_name: 'Test Evaluation',
    generation_id: 'gen-1',
    trace_id: 'trace-1',
    timestamp: '2024-01-01T10:00:00Z',
    result: true,
    reasoning: 'Good',
    status: 'completed',
}

describe('EvaluationRunsTable', () => {
    it.each([
        [0, undefined, undefined, false, '0', 'none'],
        [7, 'gte', 7, false, '7', 'success'],
        [7, 'lte', 7, false, '7', 'success'],
        [6, 'gte', 7, false, '6', 'danger'],
        [8, 'lte', 7, false, '8', 'danger'],
        [null, undefined, undefined, false, 'N/A', 'muted'],
        [null, undefined, undefined, true, 'Skipped', 'muted'],
    ] as const)('displays score %p with %p rule', (score, operator, threshold, skipped, label, type) => {
        expect(
            getEvaluationResultDisplay(
                { ...passingRun, result: null, result_type: 'numeric', score, applicable: score != null, skipped },
                { passingRule: operator ? { operator, threshold: threshold! } : null }
            )
        ).toMatchObject({ label, type })
    })

    let logic: ReturnType<typeof llmEvaluationLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/llm_proxy/models/': [],
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/projects/:teamId/evaluations/:id/': {},
            },
        })
        initKeaTests()
        logic = llmEvaluationLogic(props)
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        cleanup()
        logic?.unmount()
    })

    it('shows a retry action instead of the empty state when the query failed', () => {
        logic.actions.loadEvaluationRunsFailure('boom')
        renderTable()

        expect(screen.getByText('Could not load evaluation runs')).toBeInTheDocument()
        expect(screen.getByText('Retry')).toBeInTheDocument()
        expect(screen.queryByText('No evaluation runs found')).not.toBeInTheDocument()
    })

    it('warns that rows are stale when a refresh fails with runs already on screen', () => {
        logic.actions.loadEvaluationRunsSuccess([passingRun])
        logic.actions.loadEvaluationRunsFailure('boom')
        renderTable()

        expect(
            screen.getByText("We couldn't refresh the evaluation runs. The runs below may be out of date.")
        ).toBeInTheDocument()
        expect(document.querySelector('[data-attr="llma-evaluation-runs-stale-retry"]')).toBeInTheDocument()
        expect(screen.getByText('Good')).toBeInTheDocument()
    })

    it('says a filter is hiding rows when the evaluation has runs but none match', async () => {
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadEvaluationSuccess({
            output_type: 'boolean',
            output_config: { allows_na: false },
        } as EvaluationConfig)
        logic.actions.setEvaluationRunsFilter('fail', 'all')
        await expectLogic(logic).toFinishAllListeners()
        renderTable()

        expect(screen.getByText('No runs match this filter')).toBeInTheDocument()
        expect(screen.queryByText('No evaluation runs found')).not.toBeInTheDocument()
    })

    it('shows the empty state when no runs are found in the selected date range', () => {
        logic.actions.loadEvaluationRunsSuccess([])
        renderTable()

        expect(screen.getByText('No evaluation runs found')).toBeInTheDocument()
    })

    describe('opening the trace drawer', () => {
        const FLAG = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN
        const PATH = urls.aiObservabilityEvaluation('eval-123')
        const olderRun: EvaluationRun = {
            ...passingRun,
            id: 'run-2',
            generation_id: null,
            trace_id: 'trace-2',
            timestamp: '2023-01-01T10:00:00Z',
        }
        const sessionRun: EvaluationRun = {
            ...passingRun,
            id: 'run-3',
            generation_id: null,
            trace_id: '',
            session_id: 'session-1',
            reasoning: 'Session verdict',
        }

        function renderRuns(url: string = PATH): void {
            localStorage.clear()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: true })
            router.actions.push(url)
            logic.actions.loadEvaluationRunsSuccess([olderRun, passingRun, sessionRun])
            renderTable()
        }

        const targetLink = (traceId: string = 'trace-1'): Element => {
            const link = document.querySelector(`[data-attr="llma-eval-run-target-link"][href*="${traceId}"]`)
            if (!link) {
                throw new Error('No target link')
            }
            return link
        }

        it.each([
            ['the row', (): Element | null => targetLink().closest('tr')?.querySelector('td') ?? null],
            ['the target link', (): Element => targetLink()],
        ])('opens from %s on the Evals tab with the generation selected', (_name, target) => {
            renderRuns()
            const clicked = target()
            if (!clicked) {
                throw new Error('No click target')
            }

            fireEvent.click(clicked)

            expect(router.values.location.pathname).toContain(PATH)
            expect(router.values.searchParams).toEqual({ trace: 'trace-1', step: 'gen-1' })
            const { hostId } = traceDrawerLogic({ listId: 'evaluation-runs' }).values
            expect(traceViewHostLogic({ hostId }).values.detailTab).toBe('evals')
        })

        it.each([
            ['from the list', PATH],
            ['with that trace open on a step', combineUrl(PATH, { trace: 'trace-2', step: 'gen-2' }).url],
        ])('opens a trace-level run on the root of its trace %s', (_name, url) => {
            renderRuns(url)
            const linkParams = combineUrl(targetLink('trace-2').getAttribute('href') ?? '').searchParams

            fireEvent.click(targetLink('trace-2'))

            expect(linkParams).toMatchObject({ tab: 'evals' })
            expect(linkParams).not.toHaveProperty('event')
            expect(router.values.searchParams).toEqual({ trace: 'trace-2', step: 'trace-2' })
            const { fullPageHref } = traceDrawerLogic({ listId: 'evaluation-runs' }).values
            expect(combineUrl(fullPageHref ?? '').searchParams).toMatchObject({ event: 'trace-2' })
        })

        it('leaves a session run to its session link', () => {
            renderRuns()
            const sessionLink = screen.getByText(/session session-1/)
            const sessionRow = sessionLink.closest('tr')
            if (!sessionRow) {
                throw new Error('No session row')
            }

            fireEvent.click(sessionRow)
            expect(router.values.searchParams).not.toHaveProperty('trace')

            fireEvent.click(sessionLink)
            expect(router.values.location.pathname).toContain(urls.aiObservabilitySession('session-1'))
        })

        it('gives the drawer the rows with a trace in the order on screen', () => {
            renderRuns()
            const drawer = traceDrawerLogic({ listId: 'evaluation-runs' })
            expect(drawer.values.rows).toEqual([
                { traceId: 'trace-2', timestamp: null, stepId: 'trace-2' },
                { traceId: 'trace-1', timestamp: null, stepId: 'gen-1' },
            ])

            fireEvent.click(screen.getByText('Timestamp'))

            expect(drawer.values.rows.map(({ traceId }) => traceId)).toEqual(['trace-1', 'trace-2'])
        })

        it('leaves the drawer params out of the target link', () => {
            renderRuns(combineUrl(PATH, { trace: 'trace-2', ts: '2024-01-01T00:00:00Z', step: 'gen-2' }).url)

            const params = combineUrl(targetLink().getAttribute('href') ?? '').searchParams

            expect(params).toMatchObject({ tab: 'evals', event: 'gen-1' })
            expect(params).not.toHaveProperty('trace')
            expect(params).not.toHaveProperty('ts')
            expect(params).not.toHaveProperty('step')
        })
    })
})
