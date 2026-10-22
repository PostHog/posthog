/**
 * Invented data for the PostHog AI quill comparison story: one investigation told twice, once as the
 * LangGraph conversation the legacy chat renders, once as the ACP log the sandbox runner renders.
 * Nothing here comes from a real conversation.
 */
import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import {
    ArtifactContentType,
    ArtifactSource,
    AssistantMessageType,
    type RootAssistantMessage,
} from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'

import {
    OriginProduct,
    type Task,
    type TaskRun,
    TaskRunEnvironment,
    TaskRunStatus,
} from 'products/posthog_ai/frontend/types/taskTypes'
import type { StoredLogEntry } from 'products/posthog_ai/frontend/types/wireTypes'
import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

export const COMPARISON_PANEL_ID = 'quill-comparison'
export const COMPARISON_CONVERSATION_ID = 'quill-comparison-conversation'
export const COMPARISON_TASK_ID = '0199c0de-2222-7000-8000-00000000c0de'
export const COMPARISON_RUN_ID = '0199c0de-3333-7000-8000-00000000c0de'

const SIGNUP_FUNNEL_QUERY = {
    kind: NodeKind.FunnelsQuery,
    dateRange: { date_from: '-7d' },
    series: [
        { kind: NodeKind.EventsNode, event: 'landing page viewed', name: 'landing page viewed' },
        { kind: NodeKind.EventsNode, event: 'signup form opened', name: 'signup form opened' },
        { kind: NodeKind.EventsNode, event: 'email submitted', name: 'email submitted' },
        { kind: NodeKind.EventsNode, event: 'account created', name: 'account created' },
    ],
    funnelsFilter: { funnelVizType: 'steps', layout: 'horizontal' },
}

const SIGNUPS_PER_DAY_QUERY = {
    kind: NodeKind.TrendsQuery,
    dateRange: { date_from: '-14d' },
    interval: 'day',
    series: [{ kind: NodeKind.EventsNode, event: 'account created', name: 'account created' }],
}

const SIGNUPS_BY_SOURCE_QUERY = {
    kind: NodeKind.TrendsQuery,
    dateRange: { date_from: '-14d' },
    interval: 'day',
    series: [{ kind: NodeKind.EventsNode, event: 'account created', name: 'account created' }],
    breakdownFilter: { breakdown: 'utm_source', breakdown_type: 'event' },
}

const SIGNUPS_SQL = `SELECT
    toDate(timestamp) AS day,
    count() AS signups,
    countIf(properties.$browser = 'Safari') AS safari_signups
FROM events
WHERE event = 'account created'
  AND timestamp >= now() - INTERVAL 14 DAY
GROUP BY day
ORDER BY day`

const SIGNUPS_TABLE = `| day | signups | safari_signups |
| --- | ---: | ---: |
| 2024-03-04 | 412 | 96 |
| 2024-03-05 | 398 | 91 |
| 2024-03-06 | 405 | 94 |
| 2024-03-07 | 421 | 99 |
| 2024-03-08 | 389 | 88 |
| 2024-03-09 | 251 | 44 |
| 2024-03-10 | 243 | 41 |
| 2024-03-11 | 302 | 12 |
| 2024-03-12 | 288 | 9 |
| 2024-03-13 | 279 | 11 |
| 2024-03-14 | 291 | 10 |
| 2024-03-15 | 284 | 8 |`

const FINDINGS_MARKDOWN = `Signups fell **27%** week over week, and nearly all of the loss sits at one step.

### Funnel, this week vs last week

| Step | Last week | This week | Change |
| --- | ---: | ---: | ---: |
| Landing page viewed | 18,420 | 18,105 | −1.7% |
| Signup form opened | 6,210 | 6,088 | −2.0% |
| Email submitted | 3,984 | 2,610 | **−34.5%** |
| Account created | 2,803 | 2,044 | −27.1% |

### What changed

- The drop starts on **Monday the 11th**, the day the new email validation shipped.
- Safari signups fell from ~95 a day to ~10 a day. Other browsers held steady.
- The validation rejects addresses with a \`+\` sign, and Safari autofill inserts one for aliased addresses.

\`\`\`sql
${SIGNUPS_SQL}
\`\`\`

The funnel and the daily counts are below.`

const ALERT_MARKDOWN = `Done. The alert **Daily signups below trend** now fires when the day's count is more than 20% under the trailing 7-day average.

- Checks once a day at 09:00 in your project's timezone
- Notifies the \`#growth\` channel through your Slack destination
- Uses the \`account created\` event, so it tracks the same number as the funnel's last step`

export function comparisonConversationMessages(): RootAssistantMessage[] {
    return [
        {
            id: 'cmp-human-1',
            type: AssistantMessageType.Human,
            content:
                'Why did signups drop last week? Compare the signup funnel with the week before and tell me where people leave.',
            trace_id: 'cmp-trace-1',
            ui_context: {
                dashboards: [{ id: 12, name: 'Growth overview', filters: {} }],
            } as any,
        },
        {
            id: 'cmp-ai-1',
            type: AssistantMessageType.Assistant,
            content: '',
            meta: {
                thinking: [
                    {
                        type: 'thinking',
                        thinking:
                            'Compare the funnel week over week first. If one step moved much more than the others, look for a cause around that step: a release, a browser, a traffic source.',
                    },
                ],
            },
            tool_calls: [
                {
                    id: 'cmp-tool-plan',
                    type: 'tool_call',
                    name: 'todo_write',
                    args: {
                        todos: [
                            { content: 'Compare the signup funnel with the week before', status: 'completed' },
                            { content: 'Count signups per day and per browser', status: 'completed' },
                            { content: 'Match the drop against recent releases', status: 'completed' },
                            { content: 'Summarize the cause and suggest a fix', status: 'in_progress' },
                        ],
                    },
                },
                {
                    id: 'cmp-tool-funnel',
                    type: 'tool_call',
                    name: 'create_insight',
                    args: {
                        query_description: 'Signup funnel for the last 7 days compared with the 7 days before',
                        commentary: 'Comparing the signup funnel week over week',
                    },
                },
                {
                    id: 'cmp-tool-sql',
                    type: 'tool_call',
                    name: 'execute_sql',
                    args: { query: SIGNUPS_SQL, commentary: 'Counting signups per day and per browser' },
                },
                {
                    id: 'cmp-tool-search',
                    type: 'tool_call',
                    name: 'search',
                    args: {
                        kind: 'docs',
                        query: 'email validation release notes',
                        commentary: 'Checking recent releases',
                    },
                },
            ],
        },
        {
            id: 'cmp-tool-plan-result',
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'cmp-tool-plan',
            content: 'Plan updated',
            ui_payload: null,
        },
        {
            id: 'cmp-tool-funnel-result',
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'cmp-tool-funnel',
            content: 'Created the insight "Signup funnel, this week vs last week"',
            ui_payload: null,
        },
        {
            id: 'cmp-artifact-funnel',
            type: AssistantMessageType.Artifact,
            artifact_id: 'cmp-funnel-artifact',
            source: ArtifactSource.Artifact,
            content: {
                content_type: ArtifactContentType.Visualization,
                query: SIGNUP_FUNNEL_QUERY as any,
                name: 'Signup funnel, this week vs last week',
            },
        },
        {
            id: 'cmp-tool-sql-result',
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'cmp-tool-sql',
            content: SIGNUPS_TABLE,
            ui_payload: { execute_sql: SIGNUPS_SQL },
        },
        {
            id: 'cmp-tool-search-result',
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'cmp-tool-search',
            content:
                'Found 2 results: "Stricter email validation on signup" (changelog, 11 Mar) and "Signup form: autofill support" (docs).',
            ui_payload: null,
        },
        {
            id: 'cmp-ai-2',
            type: AssistantMessageType.Assistant,
            content: FINDINGS_MARKDOWN,
        },
        {
            id: 'cmp-multi-viz',
            type: AssistantMessageType.MultiVisualization,
            visualizations: [
                {
                    query: 'Signups per day',
                    plan: 'Signups per day, last 14 days',
                    answer: SIGNUPS_PER_DAY_QUERY as any,
                },
                {
                    query: 'Signups by source',
                    plan: 'Signups per day by traffic source',
                    answer: SIGNUPS_BY_SOURCE_QUERY as any,
                },
            ],
            commentary:
                'Both charts bend on the 11th. Paid and organic sources fall by the same share, so the cause is on the form, not in acquisition.',
        },
        {
            id: 'cmp-human-2',
            type: AssistantMessageType.Human,
            content: 'Set up an alert when daily signups fall more than 20% below the 7-day average.',
            trace_id: 'cmp-trace-2',
        },
        {
            id: 'cmp-failure-1',
            type: AssistantMessageType.Failure,
            content: 'PostHog AI could not reach the alerts service. Please try again.',
        },
        {
            id: 'cmp-human-3',
            type: AssistantMessageType.Human,
            content: 'Set up an alert when daily signups fall more than 20% below the 7-day average.',
            trace_id: 'cmp-trace-3',
        },
        {
            id: 'cmp-ai-3',
            type: AssistantMessageType.Assistant,
            content: ALERT_MARKDOWN,
            tool_calls: [
                {
                    id: 'cmp-tool-alert',
                    type: 'tool_call',
                    name: 'create_insight',
                    args: {
                        query_description: 'Daily signups with a 7-day moving average',
                        commentary: 'Creating the alert on daily signups',
                    },
                },
            ],
            meta: {
                form: {
                    options: [
                        { value: 'Show me recordings of Safari users who left at the email step' },
                        { value: 'Also alert on activation drops' },
                    ],
                },
            },
        },
        {
            id: 'cmp-tool-alert-result',
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'cmp-tool-alert',
            content: 'Created the alert "Daily signups below trend"',
            ui_payload: null,
        },
    ] as RootAssistantMessage[]
}

export function comparisonConversation(): Record<string, unknown> {
    return {
        id: COMPARISON_CONVERSATION_ID,
        status: 'idle',
        title: 'Why did signups drop last week?',
        agent_runtime: 'langgraph',
        created_at: '2024-03-15T14:02:10.000000Z',
        updated_at: '2024-03-15T14:06:40.000000Z',
        user: MOCK_DEFAULT_BASIC_USER,
        messages: comparisonConversationMessages(),
    }
}

// --- Sandbox runtime -------------------------------------------------------------------------------------

function notification(timestamp: string, method: string, params: Record<string, unknown>): StoredLogEntry {
    return { type: 'notification', timestamp, notification: { method, params } }
}

function update(timestamp: string, sessionUpdate: Record<string, unknown>): StoredLogEntry {
    return notification(timestamp, 'session/update', { update: sessionUpdate })
}

function userMessage(timestamp: string, text: string): StoredLogEntry {
    return update(timestamp, { sessionUpdate: 'user_message_chunk', content: { type: 'text', text } })
}

function agentMessage(timestamp: string, messageId: string, text: string): StoredLogEntry {
    return update(timestamp, { sessionUpdate: 'agent_message_chunk', messageId, content: { type: 'text', text } })
}

function agentThought(timestamp: string, text: string): StoredLogEntry {
    return update(timestamp, { sessionUpdate: 'agent_thought_chunk', content: { type: 'text', text } })
}

function toolCall(
    timestamp: string,
    id: string,
    toolName: string,
    title: string,
    rawInput: Record<string, unknown>,
    kind?: string
): StoredLogEntry {
    return update(timestamp, {
        sessionUpdate: 'tool_call',
        toolCallId: id,
        title,
        kind,
        status: 'in_progress',
        rawInput,
        _meta: { claudeCode: { toolName } },
    })
}

function posthogCall(timestamp: string, id: string, tool: string, args: object, context: string): StoredLogEntry {
    return update(timestamp, {
        sessionUpdate: 'tool_call',
        toolCallId: id,
        title: 'exec',
        kind: 'other',
        status: 'in_progress',
        rawInput: { command: `call ${tool} ${JSON.stringify(args)}`, context },
        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    })
}

function toolResult(timestamp: string, id: string, status: string, text: string, rawOutput?: unknown): StoredLogEntry {
    return update(timestamp, {
        sessionUpdate: 'tool_call_update',
        toolCallId: id,
        status,
        content: [{ type: 'content', content: { type: 'text', text } }],
        ...(rawOutput !== undefined ? { rawOutput } : {}),
    })
}

export function comparisonRunLog(): StoredLogEntry[] {
    return [
        userMessage(
            '2024-03-15T14:02:10Z',
            'Why did signups drop last week? Compare the signup funnel with the week before and tell me where people leave.'
        ),
        notification('2024-03-15T14:02:11Z', '_posthog/status', { status: 'sdk_initialization' }),
        agentThought(
            '2024-03-15T14:02:12Z',
            'Compare the funnel week over week first. If one step moved much more than the others, look for a cause around that step.'
        ),
        toolCall(
            '2024-03-15T14:02:13Z',
            'cmp-run-plan',
            'TodoWrite',
            'Update plan',
            {
                todos: [
                    { content: 'Compare the signup funnel with the week before', status: 'completed' },
                    { content: 'Count signups per day and per browser', status: 'completed' },
                    { content: 'Match the drop against recent releases', status: 'completed' },
                    { content: 'Summarize the cause and suggest a fix', status: 'in_progress' },
                ],
            },
            'other'
        ),
        toolResult('2024-03-15T14:02:13Z', 'cmp-run-plan', 'completed', 'Plan updated'),
        posthogCall(
            '2024-03-15T14:02:17Z',
            'cmp-run-sql',
            'execute-sql',
            { query: SIGNUPS_SQL },
            'Count signups per day and per browser'
        ),
        toolResult('2024-03-15T14:02:19Z', 'cmp-run-sql', 'completed', SIGNUPS_TABLE, {
            query: { kind: NodeKind.HogQLQuery, query: SIGNUPS_SQL },
            results: { columns: ['day', 'signups', 'safari_signups'] },
        }),
        toolCall(
            '2024-03-15T14:02:20Z',
            'cmp-run-grep',
            'Grep',
            'Search the changelog for the email validation release',
            { pattern: 'email validation', path: 'changelog/' },
            'search'
        ),
        toolResult(
            '2024-03-15T14:02:21Z',
            'cmp-run-grep',
            'completed',
            'changelog/2024-03-11.md:3: Stricter email validation on signup'
        ),
        toolCall(
            '2024-03-15T14:02:22Z',
            'cmp-run-read',
            'Read',
            'Read emailValidator.ts',
            { file_path: 'frontend/src/signup/emailValidator.ts' },
            'read'
        ),
        toolResult(
            '2024-03-15T14:02:23Z',
            'cmp-run-read',
            'completed',
            'export const EMAIL_PATTERN = /^[a-z0-9._-]+@[a-z0-9.-]+\\.[a-z]{2,}$/i'
        ),
        // The quill thread keeps only the last finished call of a run unfolded, so the chart goes last.
        posthogCall(
            '2024-03-15T14:02:24Z',
            'cmp-run-funnel',
            'query-funnel',
            { series: SIGNUP_FUNNEL_QUERY.series, dateRange: SIGNUP_FUNNEL_QUERY.dateRange },
            'Compare the signup funnel week over week'
        ),
        toolResult('2024-03-15T14:02:26Z', 'cmp-run-funnel', 'completed', 'Funnel with 4 steps', {
            query: SIGNUP_FUNNEL_QUERY,
            _posthogUrl: '/project/1/insights/new',
        }),
        agentMessage('2024-03-15T14:02:30Z', 'cmp-run-findings', FINDINGS_MARKDOWN),
        notification('2024-03-15T14:02:31Z', '_posthog/turn_complete', {}),
        userMessage(
            '2024-03-15T14:05:00Z',
            'Set up an alert when daily signups fall more than 20% below the 7-day average.'
        ),
        posthogCall(
            '2024-03-15T14:05:02Z',
            'cmp-run-alert-failed',
            'alert-create',
            { name: 'Daily signups below trend', threshold: { type: 'percentage', lower: -20 } },
            'Create the alert on daily signups'
        ),
        toolResult(
            '2024-03-15T14:05:04Z',
            'cmp-run-alert-failed',
            'failed',
            'alerts service returned 503: temporarily unavailable'
        ),
        posthogCall(
            '2024-03-15T14:05:05Z',
            'cmp-run-alert',
            'alert-create',
            { name: 'Daily signups below trend', threshold: { type: 'percentage', lower: -20 } },
            'Retry creating the alert'
        ),
        toolResult('2024-03-15T14:05:07Z', 'cmp-run-alert', 'completed', 'Created alert "Daily signups below trend"', {
            id: 'alert-42',
            name: 'Daily signups below trend',
            _posthogUrl: '/project/1/alerts/alert-42',
        }),
        agentMessage('2024-03-15T14:05:09Z', 'cmp-run-alert-answer', ALERT_MARKDOWN),
        notification('2024-03-15T14:05:10Z', '_posthog/turn_complete', {}),
    ]
}

export function comparisonRun(): TaskRun {
    return {
        id: COMPARISON_RUN_ID,
        task: COMPARISON_TASK_ID,
        stage: null,
        branch: null,
        status: TaskRunStatus.COMPLETED,
        environment: TaskRunEnvironment.CLOUD,
        runtime_adapter: null,
        model: null,
        reasoning_effort: null,
        log_url: null,
        error_message: null,
        output: null,
        task_summary: null,
        task_tags: [],
        state: {},
        artifacts: [],
        created_at: '2024-03-15T14:02:05Z',
        updated_at: '2024-03-15T14:05:10Z',
        completed_at: '2024-03-15T14:05:10Z',
    }
}

export function comparisonTask(): Task {
    return {
        id: COMPARISON_TASK_ID,
        task_number: 7,
        slug: 'TASK-7',
        title: 'Why did signups drop last week?',
        description:
            'Why did signups drop last week? Compare the signup funnel with the week before and tell me where people leave.',
        origin_product: OriginProduct.USER_CREATED,
        runtime: TaskRuntimeEnumApi.Acp,
        repository: null,
        github_integration: null,
        signal_report: null,
        json_schema: null,
        internal: false,
        latest_run: comparisonRun(),
        created_at: '2024-03-15T14:02:05Z',
        updated_at: '2024-03-15T14:05:10Z',
        created_by: {
            id: MOCK_DEFAULT_BASIC_USER.id,
            uuid: MOCK_DEFAULT_BASIC_USER.uuid,
            distinct_id: MOCK_DEFAULT_BASIC_USER.distinct_id,
            first_name: MOCK_DEFAULT_BASIC_USER.first_name,
            email: MOCK_DEFAULT_BASIC_USER.email,
        },
    }
}

/** The JSONL body the `logs/` endpoint returns. */
export function comparisonRunLogBody(): string {
    return comparisonRunLog()
        .map((entry) => JSON.stringify(entry))
        .join('\n')
}

// --- Query API ---------------------------------------------------------------------------------------------

const DAYS = Array.from({ length: 14 }, (_, index) => `2024-03-${String(2 + index).padStart(2, '0')}`)
const SIGNUPS = [418, 402, 412, 398, 405, 421, 389, 251, 243, 302, 288, 279, 291, 284]

function dayLabel(day: string): string {
    const [, month, date] = day.split('-')
    return `${Number(date)}-${month === '03' ? 'Mar' : month}-2024`
}

function trendSeries(label: string, data: number[], breakdownValue?: string): Record<string, unknown> {
    return {
        action: { id: 'account created', type: 'events', order: 0, name: 'account created', properties: {} },
        label,
        count: data.reduce((sum, value) => sum + value, 0),
        data,
        labels: DAYS.map(dayLabel),
        days: DAYS,
        ...(breakdownValue !== undefined ? { breakdown_value: breakdownValue } : {}),
    }
}

function funnelStep(name: string, order: number, count: number): Record<string, unknown> {
    return {
        action_id: name,
        name,
        custom_name: null,
        order,
        people: [],
        count,
        type: 'events',
        average_conversion_time: order === 0 ? null : 120 * order,
        median_conversion_time: order === 0 ? null : 90 * order,
    }
}

function sourceOf(query: Record<string, unknown>): Record<string, unknown> {
    const source = query.source
    return source && typeof source === 'object' ? (source as Record<string, unknown>) : query
}

/** The query API's answer for every query the comparison story runs; `null` for a query it does not know. */
export function comparisonQueryResponse(query: Record<string, unknown>): Record<string, unknown> | null {
    const source = sourceOf(query)
    switch (source.kind) {
        case NodeKind.FunnelsQuery:
            return {
                results: [
                    funnelStep('landing page viewed', 0, 18105),
                    funnelStep('signup form opened', 1, 6088),
                    funnelStep('email submitted', 2, 2610),
                    funnelStep('account created', 3, 2044),
                ],
            }
        case NodeKind.TrendsQuery: {
            const breakdown = source.breakdownFilter as { breakdown?: string } | undefined
            if (breakdown?.breakdown) {
                return {
                    results: [
                        trendSeries(
                            'account created - organic',
                            SIGNUPS.map((value) => Math.round(value * 0.46)),
                            'organic'
                        ),
                        trendSeries(
                            'account created - paid',
                            SIGNUPS.map((value) => Math.round(value * 0.34)),
                            'paid'
                        ),
                        trendSeries(
                            'account created - referral',
                            SIGNUPS.map((value) => Math.round(value * 0.2)),
                            'referral'
                        ),
                    ],
                }
            }
            return { results: [trendSeries('account created', SIGNUPS)] }
        }
        case NodeKind.HogQLQuery:
            return {
                columns: ['day', 'signups', 'safari_signups'],
                types: [
                    ['day', 'Date'],
                    ['signups', 'UInt64'],
                    ['safari_signups', 'UInt64'],
                ],
                results: DAYS.map((day, index) => [
                    day,
                    SIGNUPS[index],
                    index < 9 ? Math.round(SIGNUPS[index] * 0.23) : 10,
                ]),
                hogql: SIGNUPS_SQL,
            }
        default:
            return null
    }
}
