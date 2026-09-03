import { evaluationsList, llmAnalyticsEvaluationReportsList } from '../generated/api'
import type { EvaluationApi, EvaluationReportApi } from '../generated/api.schemas'
import { listAllEvaluationReports, listAllEvaluations } from './evaluationsApi'

jest.mock('../generated/api', () => ({
    evaluationsList: jest.fn(),
    evaluationsPartialUpdate: jest.fn(),
    llmAnalyticsEvaluationReportsList: jest.fn(),
}))

const evaluationApi = (id: string): EvaluationApi => ({
    id,
    name: `Evaluation ${id}`,
    description: '',
    directory_id: null,
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Check correctness' },
    output_type: 'boolean',
    output_config: {},
    conditions: [],
    target: 'generation',
    model_configuration: {
        provider: 'openai',
        model: 'gpt-5-mini',
        provider_key_id: null,
        provider_key_name: null,
    },
    created_at: `2024-01-0${id}T00:00:00Z`,
    updated_at: `2024-01-0${id}T00:00:00Z`,
    created_by: {
        id: 1,
        uuid: '00000000-0000-0000-0000-000000000001',
        email: 'user@example.com',
        hedgehog_config: null,
    },
    deleted: false,
    user_access_level: 'editor',
})

const evaluationReportApi = (id: string, evaluation: string): EvaluationReportApi => ({
    id,
    evaluation,
    frequency: 'scheduled',
    rrule: 'FREQ=DAILY',
    starts_at: '2024-01-01T00:00:00Z',
    timezone_name: 'UTC',
    next_delivery_date: '2024-01-02T00:00:00Z',
    delivery_targets: [],
    max_sample_size: 200,
    enabled: true,
    deleted: false,
    last_delivered_at: null,
    generated_report_count: 0,
    last_generated_at: null,
    report_prompt_guidance: '',
    trigger_threshold: null,
    cooldown_minutes: 60,
    daily_run_cap: 10,
    created_by: null,
    created_at: '2024-01-01T00:00:00Z',
})

describe('evaluationsApi', () => {
    beforeEach(() => {
        jest.mocked(evaluationsList).mockReset()
        jest.mocked(llmAnalyticsEvaluationReportsList).mockReset()
    })

    it('loads every evaluations page', async () => {
        jest.mocked(evaluationsList)
            .mockResolvedValueOnce({
                count: 2,
                next: '/api/projects/1/evaluations/?limit=100&offset=1',
                previous: null,
                results: [evaluationApi('1')],
            })
            .mockResolvedValueOnce({
                count: 2,
                next: null,
                previous: '/api/projects/1/evaluations/?limit=100',
                results: [evaluationApi('2')],
            })

        await expect(listAllEvaluations('1')).resolves.toEqual([
            expect.objectContaining({ id: '1', evaluation_type: 'llm_judge' }),
            expect.objectContaining({ id: '2', evaluation_type: 'llm_judge' }),
        ])
        expect(evaluationsList).toHaveBeenNthCalledWith(1, '1', { limit: 100, offset: 0 })
        expect(evaluationsList).toHaveBeenNthCalledWith(2, '1', { limit: 100, offset: 1 })
    })

    it('loads every evaluation report page', async () => {
        jest.mocked(llmAnalyticsEvaluationReportsList)
            .mockResolvedValueOnce({
                count: 2,
                next: '/api/projects/1/llm_analytics/evaluation_reports/?limit=100&offset=1',
                previous: null,
                results: [evaluationReportApi('report-1', 'evaluation-1')],
            })
            .mockResolvedValueOnce({
                count: 2,
                next: null,
                previous: '/api/projects/1/llm_analytics/evaluation_reports/?limit=100',
                results: [evaluationReportApi('report-2', 'evaluation-2')],
            })

        await expect(listAllEvaluationReports('1')).resolves.toEqual([
            expect.objectContaining({ id: 'report-1', evaluation: 'evaluation-1' }),
            expect.objectContaining({ id: 'report-2', evaluation: 'evaluation-2' }),
        ])
        expect(llmAnalyticsEvaluationReportsList).toHaveBeenNthCalledWith(1, '1', { limit: 100, offset: 0 })
        expect(llmAnalyticsEvaluationReportsList).toHaveBeenNthCalledWith(2, '1', { limit: 100, offset: 1 })
    })
})
