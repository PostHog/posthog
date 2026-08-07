import { evaluationsList } from '../generated/api'
import type { EvaluationApi } from '../generated/api.schemas'
import { listAllEvaluations } from './evaluationsApi'

jest.mock('../generated/api', () => ({
    evaluationsList: jest.fn(),
    evaluationsPartialUpdate: jest.fn(),
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
})

describe('evaluationsApi', () => {
    beforeEach(() => {
        jest.mocked(evaluationsList).mockReset()
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
})
