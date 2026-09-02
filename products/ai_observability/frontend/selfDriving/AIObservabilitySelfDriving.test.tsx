import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, type AppContext } from '~/types'

import * as alertsApi from 'products/alerts/frontend/generated/api'

import * as aiObservabilityApi from '../generated/api'
import { AIObservabilitySelfDriving } from './AIObservabilitySelfDriving'

jest.mock('../generated/api', () => ({
    evaluationDirectoriesList: jest.fn(),
    evaluationsList: jest.fn(),
    llmAnalyticsEvaluationReportsList: jest.fn(),
}))

jest.mock('products/alerts/frontend/generated/api', () => ({
    alertsList: jest.fn(),
}))

jest.mock('lib/utils/newInternalTab')

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutConfigList: jest.fn(() => new Promise(() => {})),
    signalsScoutMetadataGet: jest.fn(() => new Promise(() => {})),
}))

const EVAL_REPORTS_SOURCE_CONFIG = {
    id: 'source-config-eval-reports',
    source_product: 'llm_analytics',
    source_type: 'evaluation_report',
    enabled: true,
    config: {},
}

const ANOMALY_INVESTIGATION_SOURCE_CONFIG = {
    id: 'source-config-anomaly-investigation',
    source_product: 'analytics',
    source_type: 'anomaly_investigation',
    enabled: false,
    config: {},
}

describe('AIObservabilitySelfDriving', () => {
    let patchedSourceConfigs: { id: string; enabled: boolean }[]

    beforeEach(() => {
        localStorage.clear()
        patchedSourceConfigs = []
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    {
                        results: [EVAL_REPORTS_SOURCE_CONFIG, ANOMALY_INVESTIGATION_SOURCE_CONFIG],
                        count: 2,
                        next: null,
                        previous: null,
                    },
                ],
            },
            patch: {
                '/api/projects/:team_id/signals/source_configs/:id/': async ({ request, params }) => {
                    const body = (await request.json()) as { enabled: boolean }
                    patchedSourceConfigs.push({ id: params.id as string, enabled: body.enabled })
                    const sourceConfig =
                        params.id === ANOMALY_INVESTIGATION_SOURCE_CONFIG.id
                            ? ANOMALY_INVESTIGATION_SOURCE_CONFIG
                            : EVAL_REPORTS_SOURCE_CONFIG
                    return [200, { ...sourceConfig, enabled: body.enabled }]
                },
            },
        })
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.LlmSkill]: AccessControlLevel.Editor,
            },
        } as AppContext
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI], {
            [FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI]: true,
        })
        jest.mocked(newInternalTab).mockReset()
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
                    user_access_level: 'editor',
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
                    user_access_level: 'editor',
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
        jest.mocked(alertsApi.alertsList).mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [
                {
                    id: 'alert-investigated',
                    created_by: {
                        id: 1,
                        uuid: '00000000-0000-0000-0000-000000000001',
                        email: 'person@example.com',
                        hedgehog_config: null,
                    },
                    created_at: '2024-01-01T00:00:00Z',
                    insight: 10,
                    insight_short_id: 'insight-cost',
                    insight_display_name: 'AI cost by model',
                    name: 'Unexpected AI cost',
                    subscribed_users: [],
                    threshold: {
                        id: 'threshold-investigated',
                        created_at: '2024-01-01T00:00:00Z',
                        configuration: { type: 'absolute', bounds: null },
                    },
                    state: 'Not firing',
                    enabled: true,
                    last_notified_at: null,
                    last_checked_at: '2024-01-04T00:00:00Z',
                    next_check_at: null,
                    checks: [],
                    checks_total: null,
                    last_value: null,
                    investigation_agent_enabled: true,
                    search_match_type: null,
                },
                {
                    id: 'alert-uninvestigated',
                    created_by: {
                        id: 1,
                        uuid: '00000000-0000-0000-0000-000000000001',
                        email: 'person@example.com',
                        hedgehog_config: null,
                    },
                    created_at: '2024-01-02T00:00:00Z',
                    insight: 11,
                    insight_short_id: 'insight-errors',
                    insight_display_name: 'AI errors by model',
                    name: 'Unexpected error rate',
                    subscribed_users: [],
                    threshold: {
                        id: 'threshold-uninvestigated',
                        created_at: '2024-01-02T00:00:00Z',
                        configuration: { type: 'absolute', bounds: null },
                    },
                    state: 'Not firing',
                    enabled: true,
                    last_notified_at: null,
                    last_checked_at: null,
                    next_check_at: null,
                    checks: [],
                    checks_total: null,
                    last_value: null,
                    investigation_agent_enabled: false,
                    search_match_type: null,
                },
            ],
        })
    })

    afterEach(() => {
        cleanup()
        localStorage.clear()
    })

    it('renders scout templates and evaluation report status', async () => {
        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        expect(screen.getAllByText('Use template')).toHaveLength(3)

        // Counting the labels alone passes even when every button is disabled, which is what
        // happens if the scene stops granting scout-creation access. Prove one actually opens.
        await userEvent.click(screen.getByTestId('create-costly-users-scout'))
        expect(await screen.findByText('Create a scout')).toBeInTheDocument()

        const tooltipTrigger = screen.getByText('What is this?')
        await userEvent.hover(tooltipTrigger)

        expect(await screen.findByText(/Each template is a pre-defined scout/)).toBeInTheDocument()

        const docsLink = screen.getByText('Read the docs')
        expect(docsLink).toHaveAttribute('href', 'https://posthog.com/docs/ai-observability/self-driving')
        expect(docsLink).toHaveAttribute('target', '_blank')
        const introBanner = screen.getByText('Self-driving').closest('.LemonBanner')
        const inboxLink = within(introBanner as HTMLElement)
            .getByText('inbox')
            .closest('a')
        expect(inboxLink).toHaveAttribute('href', '/project/997/inbox')
        expect(inboxLink).toHaveAttribute('target', '_blank')
        expect(screen.getAllByText('ai-observability')[0].closest('p')).toHaveTextContent(
            'Add the ai-observability label to a scout for it to appear here.'
        )

        expect(await screen.findByText('Correctness check')).toBeInTheDocument()
        expect(screen.getByText('Tone check')).toBeInTheDocument()
        expect(screen.getAllByText('Enabled')).toHaveLength(2)
        expect(screen.getAllByText('Disabled')).toHaveLength(2)
        expect(
            screen.getByText(/Signals from evals are only generated if eval reports are enabled/)
        ).toBeInTheDocument()
        expect(screen.getByText('Reports generated')).toBeInTheDocument()
        expect(screen.getByText('Last generated')).toBeInTheDocument()
        expect(screen.getByText('4')).toBeInTheDocument()
        expect(screen.getAllByText('Never')).toHaveLength(2)

        const evalReportsDescription = screen.getByText(
            /Signals from evals are only generated if eval reports are enabled/
        )
        const evalReportsDocsLink = within(evalReportsDescription).getByText('Learn more').closest('a')
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
        expect(editLinks[0]).toHaveAttribute('target', '_blank')
        expect(editLinks[1]).toHaveAttribute(
            'href',
            '/project/997/ai-evals/evaluations/evaluation-disabled?evaluation_tab=configuration'
        )
        expect(editLinks[1]).toHaveAttribute('target', '_blank')

        expect(screen.getByText('Anomaly alert investigations')).toBeInTheDocument()
        const anomalyInvestigationsDescription = screen.getByText(
            /Insights with anomaly detection alerts that have agent investigation enabled/
        )
        const anomalyInvestigationsDocsLink = within(anomalyInvestigationsDescription).getByText('Learn more')
        expect(anomalyInvestigationsDocsLink).toHaveAttribute(
            'href',
            'https://posthog.com/docs/ai-observability/self-driving#anomaly-investigations'
        )
        expect(anomalyInvestigationsDocsLink).toHaveAttribute('target', '_blank')
        expect(alertsApi.alertsList).toHaveBeenCalledWith('997', {
            has_detector: true,
            insight_tag: 'ai-observability',
            limit: 100,
            offset: 0,
        })
        const anomalyTable = document.querySelector('[data-attr="anomaly-alert-investigations-table"]')
        expect(anomalyTable).toBeInTheDocument()
        const anomalyTableQueries = within(anomalyTable as HTMLElement)
        expect(anomalyTableQueries.getByText('Unexpected AI cost')).toBeInTheDocument()
        expect(anomalyTableQueries.getByText('Unexpected error rate')).toBeInTheDocument()
        expect(anomalyTableQueries.getByText('AI cost by model').closest('a')).toHaveAttribute(
            'href',
            '/project/997/insights/insight-cost'
        )
        expect(anomalyTableQueries.getByText('AI errors by model').closest('a')).toHaveAttribute(
            'href',
            '/project/997/insights/insight-errors'
        )
        const anomalyEditLinks = anomalyTableQueries.getAllByText('Edit').map((button) => button.closest('a'))
        expect(anomalyEditLinks[0]).toHaveAttribute(
            'href',
            '/project/997/alerts?alert_type=insights&alert_id=alert-investigated'
        )
        expect(anomalyEditLinks[0]).toHaveAttribute('target', '_blank')
        expect(anomalyEditLinks[1]).toHaveAttribute(
            'href',
            '/project/997/alerts?alert_type=insights&alert_id=alert-uninvestigated'
        )
        expect(anomalyEditLinks[1]).toHaveAttribute('target', '_blank')

        await userEvent.click(screen.getByText('Correctness check'))
        expect(newInternalTab).toHaveBeenLastCalledWith(
            '/ai-evals/evaluations/evaluation-enabled?evaluation_tab=configuration'
        )

        await userEvent.click(anomalyTableQueries.getByText('Unexpected AI cost'))
        expect(newInternalTab).toHaveBeenLastCalledWith('/alerts?alert_type=insights&alert_id=alert-investigated')
    })

    // Both sections render the same switch, so a section wired to the other section's signal
    // source would still look right. This pins each switch to the config it reads and writes.
    it('reads and writes each section signal source', async () => {
        const successToast = jest.spyOn(lemonToast, 'success').mockReturnValue('signal-source-toggle')

        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        const evalReportsSwitch = await screen.findByTestId('self-driving-eval-reports-signal-source')
        const anomalySwitch = screen.getByTestId('self-driving-anomaly-investigation-signal-source')
        expect(evalReportsSwitch).toHaveAttribute('aria-checked', 'true')
        expect(anomalySwitch).toHaveAttribute('aria-checked', 'false')

        await userEvent.click(screen.getByText('AI observability signal source'))
        expect(patchedSourceConfigs).toEqual([])
        expect(evalReportsSwitch).toHaveAttribute('aria-checked', 'true')

        await userEvent.click(anomalySwitch)
        await waitFor(() =>
            expect(patchedSourceConfigs).toEqual([{ id: 'source-config-anomaly-investigation', enabled: true }])
        )
        expect(successToast).toHaveBeenCalledWith('Product analytics signal source enabled')
        await waitFor(() => expect(anomalySwitch).not.toBeDisabled())

        await userEvent.click(evalReportsSwitch)
        await waitFor(() =>
            expect(patchedSourceConfigs).toEqual([
                { id: 'source-config-anomaly-investigation', enabled: true },
                { id: 'source-config-eval-reports', enabled: false },
            ])
        )
        expect(successToast).toHaveBeenCalledWith('AI observability signal source disabled')
        successToast.mockRestore()
    })

    it('offers a retry when signal source configs fail to load', async () => {
        let sourceConfigRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => {
                    sourceConfigRequests += 1
                    if (sourceConfigRequests === 1) {
                        return [500, { detail: 'Failed to load signal source settings' }]
                    }
                    return [
                        200,
                        {
                            results: [EVAL_REPORTS_SOURCE_CONFIG, ANOMALY_INVESTIGATION_SOURCE_CONFIG],
                            count: 2,
                            next: null,
                            previous: null,
                        },
                    ]
                },
            },
        })
        silenceKeaLoadersErrors()

        try {
            render(
                <Provider>
                    <AIObservabilitySelfDriving />
                </Provider>
            )

            const loadErrors = await screen.findAllByText(
                "We couldn't load signal source settings. Try again in a moment."
            )
            expect(loadErrors).toHaveLength(2)

            await userEvent.click(screen.getAllByText('Try again')[0])

            expect(await screen.findByTestId('self-driving-eval-reports-signal-source')).toHaveAttribute(
                'aria-checked',
                'true'
            )
            expect(sourceConfigRequests).toBe(2)
        } finally {
            resumeKeaLoadersErrors()
        }
    })

    it('sorts eval and anomaly alert columns', async () => {
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

        const anomalyAlertNames = (): string[] =>
            Array.from(
                document.querySelectorAll(
                    '[data-attr="anomaly-alert-investigations-table"] tbody tr td:first-child span:first-child'
                )
            ).map((nameSpan) => nameSpan.textContent ?? '')

        expect(anomalyAlertNames()).toEqual(['Unexpected AI cost', 'Unexpected error rate'])

        await userEvent.click(screen.getByText('Last checked'))
        expect(anomalyAlertNames()).toEqual(['Unexpected AI cost', 'Unexpected error rate'])
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

    it('links the empty anomaly state guidance', async () => {
        jest.mocked(alertsApi.alertsList).mockResolvedValueOnce({
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

        const emptyStateCopy = await screen.findByText(/No anomaly alerts match this view/)
        const insightLink = within(emptyStateCopy).getByText('insight').closest('a')
        expect(insightLink).toHaveAttribute('href', '/project/997/insights')
        expect(insightLink).toHaveAttribute('target', '_blank')
        expect(screen.getByText('AI observability dashboard').closest('a')).toHaveAttribute(
            'href',
            '/project/997/ai-observability/dashboard'
        )
        expect(screen.getByText('AI observability dashboard').closest('a')).toHaveAttribute('target', '_blank')
    })

    it('remembers which sections are collapsed', async () => {
        const firstRender = render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        expect(await screen.findByText('Correctness check')).toBeInTheDocument()
        const evalReportsToggle = document.querySelector('[data-attr="ai-observability-eval-reports-collapse"]')
        expect(evalReportsToggle?.closest('.LemonCollapsePanel')).toHaveAttribute('aria-expanded', 'true')

        await userEvent.click(evalReportsToggle as HTMLElement)
        expect(evalReportsToggle?.closest('.LemonCollapsePanel')).toHaveAttribute('aria-expanded', 'false')

        firstRender.unmount()
        initKeaTests()

        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        const restoredEvalReportsToggle = document.querySelector('[data-attr="ai-observability-eval-reports-collapse"]')
        expect(restoredEvalReportsToggle?.closest('.LemonCollapsePanel')).toHaveAttribute('aria-expanded', 'false')
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
