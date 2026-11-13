import type { EvaluationConfig } from '../types'
import type { ChecklistItem, PreviewStep } from './creationChecklist'
import type { PreviewRun } from './previewRuns'

export const PANEL_WIDTH = 352
export const NARROW_PANEL_WIDTH = 272

export const STORY_STEPS: PreviewStep[] = [
    { key: 'name', title: 'Evaluate', part: 'method', checks: ['name'] },
    { key: 'output', title: 'Returns', part: 'output', checks: ['result'] },
    { key: 'traffic', title: 'Runs on', part: 'triggers', checks: ['sampling'] },
    { key: 'check', title: 'Check', part: 'model', checks: ['criteria', 'model'] },
    { key: 'reports', title: 'Reports', part: 'reports', checks: [] },
]

export const STORY_JUDGE = {
    name: 'Helpfulness',
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Is the answer helpful?' },
    output_type: 'boolean',
    output_config: {},
    conditions: [{ id: 'c1', rollout_percentage: 100, properties: [] }],
    target: 'generation',
    target_config: {},
    model_configuration: { provider: 'openai', model: 'gpt-5-mini', provider_key_id: 'key-1' },
} as unknown as EvaluationConfig

export const STORY_HOG = {
    ...STORY_JUDGE,
    name: 'Mentions a refund',
    evaluation_type: 'hog',
    evaluation_config: { source: '' },
    target: 'trace',
    model_configuration: null,
} as unknown as EvaluationConfig

export function storyChecklist(
    overrides: Partial<Record<ChecklistItem['key'], Partial<ChecklistItem>>>
): ChecklistItem[] {
    const items: ChecklistItem[] = [
        { key: 'name', label: 'Name', done: true, todo: 'Give the evaluation a name' },
        { key: 'sampling', label: 'Sampling', done: true, todo: 'Set a sampling percentage between 0.1% and 100%' },
        { key: 'criteria', label: 'Code', done: true, todo: 'Add the Hog code that returns the result' },
    ]
    return items.map((item) => ({ ...item, ...overrides[item.key] }))
}

const QUESTIONS = ['How do I reset my password?', 'Summarize this invoice', 'Which plan includes SSO?']

export function storyRuns(results: (PreviewRun['result'] | null)[]): PreviewRun[] {
    return results.map((result, index) => ({
        id: `run-${index}`,
        title: `"${QUESTIONS[index % QUESTIONS.length]}"`,
        href: `/ai-observability/traces/trace-${index}`,
        timestamp: '2026-10-19T14:00:00Z',
        result,
        drawerRow: null,
    }))
}
