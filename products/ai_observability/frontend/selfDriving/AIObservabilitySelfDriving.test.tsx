import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'
import type { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as aiObservabilityApi from '../generated/api'
import { AIObservabilitySelfDriving } from './AIObservabilitySelfDriving'

jest.mock('../generated/api', () => ({
    evaluationDirectoriesList: jest.fn(),
    evaluationsList: jest.fn(),
    llmAnalyticsEvaluationReportsList: jest.fn(),
}))

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutConfigList: jest.fn(() => new Promise(() => {})),
    signalsScoutMetadataGet: jest.fn(() => new Promise(() => {})),
}))

jest.mock('products/signals/frontend/inbox/components/config/scouts/ScoutCreateButton', () => ({
    ScoutCreateButton: ({ children }: { children: ReactNode }) => <button>{children}</button>,
}))

describe('AIObservabilitySelfDriving', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI], {
            [FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI]: true,
        })
        jest.mocked(aiObservabilityApi.evaluationDirectoriesList).mockResolvedValue([])
        jest.mocked(aiObservabilityApi.evaluationsList).mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [
                {
                    id: 'evaluation-enabled',
                    name: 'Correctness check',
                    description: 'Checks whether answers are correct.',
                    enabled: true,
                    status: 'active',
                    status_reason: null,
                    status_reason_detail: null,
                    evaluation_type: 'llm_judge',
                    evaluation_config: { prompt: 'Is the answer correct?' },
                    output_type: 'boolean',
                    output_config: {},
                    conditions: [],
                    target: 'generation',
                    model_configuration: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                    created_by: null,
                    deleted: false,
                },
                {
                    id: 'evaluation-disabled',
                    name: 'Tone check',
                    description: 'Checks the tone of each answer.',
                    enabled: true,
                    status: 'active',
                    status_reason: null,
                    status_reason_detail: null,
                    evaluation_type: 'hog',
                    evaluation_config: { source: 'return true' },
                    output_type: 'boolean',
                    output_config: {},
                    conditions: [],
                    target: 'generation',
                    model_configuration: null,
                    created_at: '2024-01-02T00:00:00Z',
                    updated_at: '2024-01-02T00:00:00Z',
                    created_by: null,
                    deleted: false,
                },
            ],
        })
        jest.mocked(aiObservabilityApi.llmAnalyticsEvaluationReportsList).mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: 'report-enabled',
                    evaluation: 'evaluation-enabled',
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
                    generated_report_count: 4,
                    last_generated_at: '2024-01-03T00:00:00Z',
                    report_prompt_guidance: '',
                    trigger_threshold: null,
                    cooldown_minutes: 60,
                    daily_run_cap: 10,
                    created_by: null,
                    created_at: '2024-01-01T00:00:00Z',
                },
            ],
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('renders scout templates and evaluation report status', async () => {
        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        expect(screen.getAllByText('Use template')).toHaveLength(3)

        const tooltipTrigger = screen.getByText('What is this?')
        await userEvent.hover(tooltipTrigger)

        expect(await screen.findByText(/Each template is a pre-defined scout/)).toBeInTheDocument()

        const docsLink = screen.getByText('Read the docs')
        expect(docsLink).toHaveAttribute('href', 'https://posthog.com/docs/ai-observability/self-driving')
        expect(docsLink).toHaveAttribute('target', '_blank')
        expect(screen.getByText('ai-observability').closest('p')).toHaveTextContent(
            'Add the ai-observability label to a scout for it to appear here.'
        )

        expect(await screen.findByText('Correctness check')).toBeInTheDocument()
        expect(screen.getByText('Tone check')).toBeInTheDocument()
        expect(screen.getByText('Enabled')).toBeInTheDocument()
        expect(screen.getByText('Disabled')).toBeInTheDocument()
        expect(
            screen.getByText(/Signals from evals are only generated if eval reports are enabled/)
        ).toBeInTheDocument()
        expect(screen.getByText('Reports generated')).toBeInTheDocument()
        expect(screen.getByText('Last generated')).toBeInTheDocument()
        expect(screen.getByText('4')).toBeInTheDocument()
        expect(screen.getAllByText('Never')).toHaveLength(1)

        const evalReportsDocsLink = screen.getByText('Learn more').closest('a')
        expect(evalReportsDocsLink).toHaveAttribute(
            'href',
            'https://posthog.com/docs/ai-observability/self-driving#eval-reports'
        )
        expect(evalReportsDocsLink).toHaveAttribute('target', '_blank')

        const editLinks = screen.getAllByText('Edit').map((button) => button.closest('a'))
        expect(editLinks[0]).toHaveAttribute(
            'href',
            '/project/997/ai-evals/evaluations/evaluation-enabled?evaluation_tab=configuration'
        )
        expect(editLinks[1]).toHaveAttribute(
            'href',
            '/project/997/ai-evals/evaluations/evaluation-disabled?evaluation_tab=configuration'
        )

        await userEvent.click(screen.getByText('Correctness check'))
        expect(router.values.location.pathname).toBe('/project/997/ai-evals/evaluations/evaluation-enabled')
        expect(router.values.searchParams).toEqual(expect.objectContaining({ evaluation_tab: 'configuration' }))
    })

    it('sorts evals by report columns', async () => {
        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        const evalNames = (): string[] =>
            Array.from(
                document.querySelectorAll(
                    '[data-attr="ai-observability-evaluations-table"] tbody tr td:first-child span:first-child'
                )
            ).map((nameSpan) => nameSpan.textContent ?? '')

        expect(await screen.findByText('Correctness check')).toBeInTheDocument()
        expect(evalNames()).toEqual(['Correctness check', 'Tone check'])

        // The eval with no report counts as zero, so ascending order puts it first.
        await userEvent.click(screen.getByText('Reports generated'))
        expect(evalNames()).toEqual(['Tone check', 'Correctness check'])

        await userEvent.click(screen.getByText('Reports generated'))
        expect(evalNames()).toEqual(['Correctness check', 'Tone check'])
    })

    it('guides users without evals to templates or their agent', async () => {
        jest.mocked(aiObservabilityApi.evaluationsList).mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })

        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        expect(await screen.findByText("You don't have any evals yet")).toBeInTheDocument()
        const createEvalButton = screen.getByText('Create an eval')
        expect(createEvalButton.closest('a')).toHaveAttribute('href', '/project/997/ai-evals/evaluations')
        expect(screen.getByText(/Use the connected PostHog MCP server/)).toBeInTheDocument()
        expect(document.querySelector('[data-attr="ai-observability-evaluations-table"]')).not.toBeInTheDocument()
    })

    it('shows a retry instead of the empty state when evals fail to load', async () => {
        const consoleError = jest.spyOn(console, 'error').mockImplementation()
        jest.mocked(aiObservabilityApi.evaluationsList).mockRejectedValueOnce(new Error('Request failed'))

        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        const errorMessage = await screen.findByText("We couldn't load your evals. Try again in a moment.")
        expect(errorMessage).toBeInTheDocument()
        expect(screen.queryByText("You don't have any evals yet")).not.toBeInTheDocument()

        const errorBanner = errorMessage.closest('.LemonBanner')
        expect(errorBanner).toBeInTheDocument()
        const retryButton = errorBanner?.querySelector('button')
        expect(retryButton).toBeInTheDocument()
        await userEvent.click(retryButton as HTMLButtonElement)

        expect(await screen.findByText('Correctness check')).toBeInTheDocument()
        expect(aiObservabilityApi.evaluationsList).toHaveBeenCalledTimes(2)
        consoleError.mockRestore()
    })
})
