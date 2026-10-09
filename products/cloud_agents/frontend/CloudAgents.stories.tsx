import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import type { UserClaudeSubscriptionApi, UserCodexIntegrationApi } from '~/generated/core/api.schemas'
import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type {
    CloudAgentCatalogApi,
    CloudAgentPresetApi,
    CloudAgentRunApi,
    CloudAgentRunEventsApi,
    CloudAgentSettingsApi,
    CloudAgentSizeApi,
    CloudAgentUsageSummaryApi,
} from './generated/api.schemas'
import { NEW_RUN_SEARCH_PARAM } from './logics/cloudAgentsNewRunLogic'

const SIZES: CloudAgentSizeApi[] = [
    { name: '1x2', vcpu: 1, memory_gib: 2, price_per_hour_usd: '0.066' },
    { name: '2x4', vcpu: 2, memory_gib: 4, price_per_hour_usd: '0.132' },
    { name: '2x8', vcpu: 2, memory_gib: 8, price_per_hour_usd: '0.184' },
    { name: '4x8', vcpu: 4, memory_gib: 8, price_per_hour_usd: '0.264' },
    { name: '4x16', vcpu: 4, memory_gib: 16, price_per_hour_usd: '0.368' },
    { name: '8x16', vcpu: 8, memory_gib: 16, price_per_hour_usd: '0.528' },
    { name: '8x32', vcpu: 8, memory_gib: 32, price_per_hour_usd: '0.736' },
    { name: '16x64', vcpu: 16, memory_gib: 64, price_per_hour_usd: '1.472' },
]

const sizeNamed = (name: CloudAgentSizeApi['name']): CloudAgentSizeApi => SIZES.find((size) => size.name === name)!

const catalog: CloudAgentCatalogApi = {
    sizes: SIZES,
    models: [
        { id: 'claude-sonnet', name: 'Claude Sonnet', runtime_adapter: 'claude', is_default: true },
        { id: 'claude-opus', name: 'Claude Opus', runtime_adapter: 'claude', is_default: false },
        { id: 'gpt-codex', name: 'GPT Codex', runtime_adapter: 'codex', is_default: false },
    ],
    inference_modes: ['auto', 'own_subscription', 'posthog'],
    rates: { vcpu_hour_usd: '0.040', memory_gib_hour_usd: '0.013', version: '2026-09' },
    limits: { max_concurrent_runs: 5, create_rate_per_hour: 60 },
}

const settings: CloudAgentSettingsApi = {
    repositories: [{ name: 'acme/web', initial_branch: null }],
    model: null,
    reasoning_effort: null,
    size: '4x16',
    inference: 'auto',
    instructions: 'Run pnpm test before you open the pull request.',
    idle_minutes: null,
    output_schema: null,
    default_preset: null,
    max_concurrent_runs: 5,
    create_rate_per_hour: 60,
    updated_at: '2026-09-01T09:00:00Z',
}

const presets: CloudAgentPresetApi[] = [
    {
        id: '0199a001-0000-7000-8000-000000000001',
        name: 'dependency-updates',
        description: 'Updates the dependencies each night and fixes what breaks.',
        repositories: [{ name: 'acme/web', initial_branch: 'main' }],
        model: null,
        reasoning_effort: 'medium',
        size: '4x16',
        inference: 'posthog',
        instructions: 'Update one package group in each pull request. Run the full test suite.',
        idle_minutes: 5,
        output_schema: null,
        tags: ['nightly', 'dependencies'],
        created_by: 1,
        created_at: '2026-08-20T10:00:00Z',
        updated_at: '2026-09-10T14:30:00Z',
    },
    {
        id: '0199a001-0000-7000-8000-000000000002',
        name: 'flaky-test-fixer',
        description: 'Finds the cause of a flaky test and fixes it.',
        repositories: [{ name: 'acme/api', initial_branch: null }],
        model: 'claude-opus',
        reasoning_effort: 'high',
        size: '8x32',
        inference: 'own_subscription',
        instructions: null,
        idle_minutes: null,
        output_schema: {
            type: 'object',
            properties: { cause: { type: 'string' }, fixed: { type: 'boolean' } },
            required: ['cause', 'fixed'],
        },
        tags: ['ci'],
        created_by: 1,
        created_at: '2026-08-28T10:00:00Z',
        updated_at: '2026-09-12T08:15:00Z',
    },
    {
        id: '0199a001-0000-7000-8000-000000000003',
        name: 'docs-sync',
        description: '',
        repositories: null,
        model: null,
        reasoning_effort: null,
        size: null,
        inference: null,
        instructions: null,
        idle_minutes: null,
        output_schema: null,
        tags: [],
        created_by: 1,
        created_at: '2026-09-02T10:00:00Z',
        updated_at: '2026-09-02T10:00:00Z',
    },
]

const makeRun = (overrides: Partial<CloudAgentRunApi>): CloudAgentRunApi => ({
    id: '0199b001-0000-7000-8000-000000000001',
    status: 'idle',
    status_reason: 'turn_closed',
    status_detail: null,
    created_at: '2026-09-14T08:00:00Z',
    started_at: '2026-09-14T08:00:20Z',
    ended_at: '2026-09-14T08:19:40Z',
    updated_at: '2026-09-14T08:19:40Z',
    prompt: 'Add a dark mode toggle to the settings page and remember the choice for each user.',
    repositories: [{ name: 'acme/web', initial_branch: 'cloud-agents/dark-mode-toggle' }],
    preset: null,
    config: {
        model: 'claude-sonnet',
        reasoning_effort: null,
        size: sizeNamed('4x16'),
        inference: 'posthog',
        create_pr: true,
        idle_minutes: 10,
        output_schema: null,
        instructions_applied: true,
    },
    result: {
        pr_url: 'https://github.com/acme/web/pull/482',
        pr_urls: ['https://github.com/acme/web/pull/482'],
        summary:
            'Added a dark mode toggle to the settings page. The choice is saved to the user preset and applied on load. All 214 tests pass.',
        output: null,
    },
    cost: {
        compute_usd: '0.1186',
        inference_usd: '0.8420',
        total_usd: '0.9606',
        vcpu_seconds: '4640',
        gib_seconds: '18560',
        billing_mode: 'billed',
        inference_billing: 'posthog',
        final: true,
    },
    agent_sessions: [
        { index: 1, status: 'ended', started_at: '2026-09-14T08:00:20Z', ended_at: '2026-09-14T08:19:40Z' },
    ],
    tags: [],
    metadata: {},
    created_by: { id: 1, email: 'dev@example.com' },
    caller: 'app',
    ...overrides,
})

const completedRun = makeRun({})

const runningRun = makeRun({
    id: '0199b001-0000-7000-8000-000000000002',
    status: 'running',
    status_reason: null,
    created_at: '2026-09-14T11:47:40Z',
    started_at: '2026-09-14T11:48:00Z',
    ended_at: null,
    prompt: 'Find why the checkout integration test is flaky and fix the cause.',
    repositories: [{ name: 'acme/api', initial_branch: 'cloud-agents/flaky-checkout-test' }],
    preset: { id: presets[1].id, name: presets[1].name },
    config: {
        ...completedRun.config,
        size: sizeNamed('8x32'),
        model: 'claude-opus',
        reasoning_effort: 'high',
        idle_minutes: 5,
    },
    result: { pr_url: null, pr_urls: [], summary: null, output: null },
    cost: {
        compute_usd: '0.1472',
        inference_usd: '0.3105',
        total_usd: '0.4577',
        vcpu_seconds: '5760',
        gib_seconds: '23040',
        billing_mode: 'billed',
        inference_billing: 'posthog',
        final: false,
    },
    agent_sessions: [{ index: 1, status: 'running', started_at: '2026-09-14T11:48:00Z', ended_at: null }],
    tags: ['ci'],
})

const failedRun = makeRun({
    id: '0199b001-0000-7000-8000-000000000003',
    status: 'idle',
    status_reason: 'unexpected_failure',
    status_detail: 'The run failed. Send a message to try again, or start a new run.',
    created_at: '2026-09-13T16:00:00Z',
    started_at: '2026-09-13T16:00:25Z',
    ended_at: '2026-09-13T16:07:05Z',
    prompt: 'Rename the billing module to payments in the whole repository.',
    repositories: [{ name: 'acme/web', initial_branch: 'main' }],
    config: { ...completedRun.config, size: sizeNamed('2x8') },
    result: { pr_url: null, pr_urls: [], summary: null, output: null },
    cost: {
        compute_usd: '0.0204',
        inference_usd: '0.1130',
        total_usd: '0.1334',
        vcpu_seconds: '800',
        gib_seconds: '3200',
        billing_mode: 'billed',
        inference_billing: 'posthog',
        final: true,
    },
    agent_sessions: [
        { index: 1, status: 'ended', started_at: '2026-09-13T16:00:25Z', ended_at: '2026-09-13T16:07:05Z' },
    ],
})

const ownSubscriptionRun = makeRun({
    id: '0199b001-0000-7000-8000-000000000004',
    created_at: '2026-09-12T09:30:00Z',
    started_at: '2026-09-12T09:30:18Z',
    ended_at: '2026-09-12T10:12:18Z',
    prompt: 'Move the date helpers to the shared utils package and update each import.',
    repositories: [{ name: 'acme/web', initial_branch: 'cloud-agents/shared-date-helpers' }],
    config: {
        ...completedRun.config,
        inference: 'own_subscription',
        size: sizeNamed('4x8'),
        output_schema: {
            type: 'object',
            properties: { moved_helpers: { type: 'integer' }, updated_imports: { type: 'integer' } },
        },
    },
    result: {
        pr_url: 'https://github.com/acme/web/pull/479',
        pr_urls: ['https://github.com/acme/web/pull/479'],
        summary: 'Moved 14 date helpers to the shared utils package and updated 63 imports.',
        output: { moved_helpers: 14, updated_imports: 63 },
    },
    cost: {
        compute_usd: '0.1848',
        inference_usd: null,
        total_usd: '0.1848',
        vcpu_seconds: '10080',
        gib_seconds: '20160',
        billing_mode: 'billed',
        inference_billing: 'own_subscription',
        final: true,
    },
    agent_sessions: [
        { index: 1, status: 'ended', started_at: '2026-09-12T09:30:18Z', ended_at: '2026-09-12T09:58:00Z' },
        { index: 2, status: 'ended', started_at: '2026-09-12T10:01:00Z', ended_at: '2026-09-12T10:12:18Z' },
    ],
})

const queuedRun = makeRun({
    id: '0199b001-0000-7000-8000-000000000005',
    status: 'queued',
    status_reason: null,
    created_at: '2026-09-14T11:59:30Z',
    started_at: null,
    ended_at: null,
    prompt: 'Update the dependencies in the mobile group.',
    repositories: [{ name: 'acme/web', initial_branch: null }],
    preset: { id: presets[0].id, name: presets[0].name },
    result: { pr_url: null, pr_urls: [], summary: null, output: null },
    cost: {
        compute_usd: '0',
        inference_usd: '0',
        total_usd: '0',
        vcpu_seconds: '0',
        gib_seconds: '0',
        billing_mode: 'billed',
        inference_billing: 'posthog',
        final: false,
    },
    agent_sessions: [],
    created_by: null,
    caller: 'api',
})

const cancelledRun = makeRun({
    id: '0199b001-0000-7000-8000-000000000006',
    status: 'done',
    status_reason: 'cancelled',
    created_at: '2026-09-11T13:00:00Z',
    started_at: '2026-09-11T13:00:22Z',
    ended_at: '2026-09-11T13:03:02Z',
    prompt: 'Try the new image pipeline on the marketing site.',
    repositories: [{ name: 'acme/marketing', initial_branch: null }],
    config: { ...completedRun.config, size: sizeNamed('1x2') },
    result: { pr_url: null, pr_urls: [], summary: null, output: null },
    cost: {
        compute_usd: '0.0029',
        inference_usd: '0.0210',
        total_usd: '0.0239',
        vcpu_seconds: '160',
        gib_seconds: '320',
        billing_mode: 'unbilled',
        inference_billing: 'posthog',
        final: true,
    },
})

const mergedRun = makeRun({
    id: '0199b001-0000-7000-8000-000000000007',
    status: 'done',
    status_reason: 'finished',
    status_detail: 'The pull request of the run was merged.',
    created_at: '2026-09-10T09:00:00Z',
    started_at: '2026-09-10T09:00:15Z',
    ended_at: '2026-09-10T09:21:15Z',
    prompt: 'Remove the unused feature flag checks from the onboarding flow.',
    result: {
        pr_url: 'https://github.com/acme/web/pull/470',
        pr_urls: ['https://github.com/acme/web/pull/470'],
        summary: 'Removed 6 flag checks from the onboarding flow.',
        output: null,
    },
})

const timedOutRun = makeRun({
    id: '0199b001-0000-7000-8000-000000000008',
    status: 'idle',
    status_reason: 'timed_out',
    status_detail: 'The run stopped because it reached its time limit. Send a message to continue.',
    created_at: '2026-09-09T14:00:00Z',
    started_at: '2026-09-09T14:00:20Z',
    ended_at: '2026-09-09T16:00:20Z',
    prompt: 'Migrate the legacy report exports to the new export service.',
    result: { pr_url: null, pr_urls: [], summary: null, output: null },
})

const runs = [queuedRun, runningRun, completedRun, failedRun, ownSubscriptionRun, timedOutRun, mergedRun, cancelledRun]

const sessionUpdate = (timestamp: string, update: Record<string, unknown>): Record<string, unknown> => ({
    type: 'notification',
    timestamp,
    notification: { jsonrpc: '2.0', method: 'session/update', params: { update } },
})

const runningEvents: Record<string, unknown>[] = [
    sessionUpdate('2026-09-14T11:48:20Z', {
        sessionUpdate: 'agent_message_chunk',
        content: { type: 'text', text: 'I will run the test a few times to see how it fails.' },
    }),
    sessionUpdate('2026-09-14T11:48:30Z', {
        sessionUpdate: 'tool_call',
        toolCallId: 'call-1',
        title: 'Bash',
        status: 'completed',
        rawInput: { command: 'pytest tests/integration/test_checkout.py --count=20 -x' },
    }),
    sessionUpdate('2026-09-14T11:50:02Z', {
        sessionUpdate: 'tool_call',
        toolCallId: 'call-2',
        title: 'Read',
        status: 'completed',
        rawInput: { file_path: 'tests/integration/test_checkout.py' },
    }),
    sessionUpdate('2026-09-14T11:51:10Z', {
        sessionUpdate: 'agent_message_chunk',
        content: {
            type: 'text',
            text: 'The test fails 3 times in 20. It reads the order before the payment event is processed. I will make the test wait for the event, and not for a fixed time.',
        },
    }),
    sessionUpdate('2026-09-14T11:51:40Z', { sessionUpdate: 'usage_snapshot', tokens: { input: 18420 } }),
    sessionUpdate('2026-09-14T11:52:00Z', {
        sessionUpdate: 'tool_call',
        toolCallId: 'call-3',
        title: 'Edit',
        status: 'in_progress',
        rawInput: { file_path: 'tests/integration/test_checkout.py' },
    }),
]

/** The stored events of a run: its prompt, then the work of the agent, then how the run ended. */
const eventsFor = (run: CloudAgentRunApi): CloudAgentRunEventsApi => ({
    truncated: false,
    events: [
        { type: 'notification', timestamp: run.created_at, notification: { method: '_posthog/sandbox_ready' } },
        sessionUpdate(run.created_at, {
            sessionUpdate: 'user_message_chunk',
            content: { type: 'text', text: run.prompt },
        }),
        ...(run.id === runningRun.id
            ? runningEvents
            : [
                  sessionUpdate(run.created_at, {
                      sessionUpdate: 'agent_message_chunk',
                      content: { type: 'text', text: 'I will read the code first, then make the change.' },
                  }),
                  sessionUpdate(run.created_at, {
                      sessionUpdate: 'tool_call',
                      toolCallId: 'call-1',
                      title: 'Bash',
                      status: 'completed',
                      rawInput: { command: 'git grep -n "settings" -- src' },
                  }),
                  sessionUpdate(run.created_at, {
                      sessionUpdate: 'tool_call',
                      toolCallId: 'call-2',
                      title: 'Bash',
                      status: run.status_reason === 'unexpected_failure' ? 'failed' : 'completed',
                      rawInput: { command: 'git push origin HEAD' },
                  }),
                  ...(run.result.summary || run.status_detail
                      ? [
                            sessionUpdate(run.created_at, {
                                sessionUpdate: 'agent_message_chunk',
                                content: { type: 'text', text: run.result.summary ?? run.status_detail },
                            }),
                        ]
                      : []),
              ]),
    ],
})

const usage: CloudAgentUsageSummaryApi = {
    date_from: '2026-08-15T00:00:00Z',
    date_to: '2026-09-14T12:00:00Z',
    group_by: 'day',
    totals: {
        runs: 86,
        compute_usd: '14.2310',
        inference_usd: '51.9040',
        total_usd: '66.1350',
        vcpu_seconds: '612000',
        gib_seconds: '2448000',
    },
    buckets: [
        ['2026-09-14', 4, '0.6120', '2.1040', '2.7160', '26400', '105600'],
        ['2026-09-13', 9, '1.4830', '5.9210', '7.4040', '63900', '255600'],
        ['2026-09-12', 12, '2.0470', '7.3350', '9.3820', '88200', '352800'],
        ['2026-09-11', 7, '1.1260', '3.8800', '5.0060', '48500', '194000'],
        ['2026-09-10', 3, '0.3090', '1.2470', '1.5560', '13300', '53200'],
    ].map(([key, runCount, compute, inference, total, vcpu, gib]) => ({
        key: String(key),
        name: null,
        usage: {
            runs: Number(runCount),
            compute_usd: String(compute),
            inference_usd: String(inference),
            total_usd: String(total),
            vcpu_seconds: String(vcpu),
            gib_seconds: String(gib),
        },
    })),
}

const claudeSubscription: UserClaudeSubscriptionApi = {
    status: 'connected',
    token_suffix: 'x9Qa',
    connected_at: '2026-08-30T10:00:00Z',
    last_used_at: '2026-09-12T10:12:18Z',
}

const codexIntegration: UserCodexIntegrationApi = { status: 'not_connected' }

const BASE = '/api/projects/:team_id/cloud_agents'

/** Every endpoint the scenes call. Each story passes the runs that its list and detail requests return. */
const cloudAgentsDecorator = (storyRuns: CloudAgentRunApi[]): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            [`${BASE}/catalog/`]: catalog,
            [`${BASE}/settings/`]: settings,
            [`${BASE}/presets/`]: toPaginatedResponse(presets),
            [`${BASE}/presets/:id/`]: presets[0],
            [`${BASE}/usage/`]: usage,
            [`${BASE}/runs/`]: toPaginatedResponse(storyRuns),
            [`${BASE}/runs/:id/`]: ({ params }) => {
                const run = storyRuns.find((candidate) => candidate.id === params.id)
                return run
                    ? [200, run]
                    : [404, { type: 'invalid_request', code: 'run_not_found', detail: 'Not found.' }]
            },
            [`${BASE}/runs/:id/events/`]: ({ params }) => {
                const run = storyRuns.find((candidate) => candidate.id === params.id)
                return [200, run ? eventsFor(run) : { events: [], truncated: false }]
            },
            '/api/users/@me/integrations/claude_subscription/': claudeSubscription,
            '/api/users/@me/integrations/codex/': codexIntegration,
        },
    })

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Cloud agents',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-14T12:00:00Z',
        featureFlags: [
            FEATURE_FLAGS.CLOUD_AGENTS,
            FEATURE_FLAGS.CLOUD_AGENTS_CLAUDE_SUBSCRIPTION_STORAGE,
            FEATURE_FLAGS.POSTHOG_CODE_CODEX_OWN_SUBSCRIPTION_CLOUD,
        ],
    },
}
export default meta

type Story = StoryObj<{}>

export const RunsList: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgents() },
}

export const RunsEmpty: Story = {
    decorators: [cloudAgentsDecorator([])],
    parameters: { pageUrl: urls.cloudAgents() },
}

export const NewRunModal: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: `${urls.cloudAgents()}?${NEW_RUN_SEARCH_PARAM}=1` },
}

export const RunRunning: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentRun(runningRun.id) },
}

export const RunCompletedWithPr: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentRun(completedRun.id) },
}

export const RunFailed: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentRun(failedRun.id) },
}

export const RunDoneMerged: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentRun(mergedRun.id) },
}

export const RunOnOwnSubscription: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentRun(ownSubscriptionRun.id) },
}

export const Presets: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentPresets() },
}

export const PresetEdit: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentPreset(presets[0].id) },
}

export const Usage: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentsUsage() },
}

export const Settings: Story = {
    decorators: [cloudAgentsDecorator(runs)],
    parameters: { pageUrl: urls.cloudAgentsSettings() },
}
