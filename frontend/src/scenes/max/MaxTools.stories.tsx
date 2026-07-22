import { CONVERSATION_ID, humanMessage, sqlQueryResponseChunk } from './__mocks__/chatResponse.mocks'
import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { HttpResponse, delay } from 'msw'
import { useEffect } from 'react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import {
    MaxErrorTrackingIssuePreview,
    MaxErrorTrackingSearchResponse,
} from '~/queries/schema/schema-assistant-error-tracking'
import {
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    MultiVisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import { ArtifactContentType, NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { FunnelsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { recordings } from '~/scenes/session-recordings/__mocks__/recordings'
import { FilterLogicalOperator, PendingApproval, PropertyFilterType, PropertyOperator } from '~/types'

import { ChangelogEntry, maxChangelogLogic } from './maxChangelogLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { Template, generateChunk, sharedMeta, useAutoSendOnce } from './maxStoriesShared'
import { maxThreadLogic } from './maxThreadLogic'

const meta: Meta = {
    title: 'Scenes-App/PostHog AI/Tools',
    ...sharedMeta,
}
export default meta

type Story = StoryObj<{}>

export const PlanningComponent: Story = {
    render: () => {
        // Planning is now derived from AssistantMessage with todo_write tool call
        const planningMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: "I'll create a comprehensive analysis plan for you.",
            id: 'planning-msg-1',
            tool_calls: [
                {
                    id: 'todo_1',
                    name: 'todo_write',
                    type: 'tool_call',
                    args: {
                        todos: [
                            {
                                content: 'Analyze user engagement metrics',
                                status: 'completed',
                                activeForm: 'Analyzing user engagement metrics',
                            },
                            {
                                content: 'Create conversion funnel visualization',
                                status: 'completed',
                                activeForm: 'Creating conversion funnel visualization',
                            },
                            {
                                content: 'Generate retention cohort analysis',
                                status: 'in_progress',
                                activeForm: 'Generating retention cohort analysis',
                            },
                            {
                                content: 'Compile comprehensive report',
                                status: 'pending',
                                activeForm: 'Compiling comprehensive report',
                            },
                            {
                                content: 'Export data to dashboard',
                                status: 'pending',
                                activeForm: 'Exporting data to dashboard',
                            },
                        ],
                    },
                },
            ],
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Create a comprehensive analysis plan',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(planningMessage)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Create a comprehensive analysis plan')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ReasoningComponent: Story = {
    render: () => {
        // Reasoning is now derived from AssistantMessage with meta.thinking
        const reasoningMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: '',
            id: 'reasoning-msg-1',
            meta: {
                thinking: [
                    {
                        type: 'thinking',
                        thinking: '*Analyzing user behavior patterns...*',
                    },
                ],
            },
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({ ...humanMessage, content: 'Analyze user engagement' })}`,
                            'event: message',
                            `data: ${JSON.stringify(reasoningMessage)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Analyze user engagement')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const TaskExecutionComponent: Story = {
    render: () => {
        // Task execution is now derived from AssistantMessage with regular tool calls
        const taskExecutionMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Executing analysis tasks...',
            id: 'task-exec-msg-1',
            tool_calls: [
                {
                    id: 'task_1',
                    name: 'create_insight',
                    type: 'tool_call',
                    args: {},
                },
                {
                    id: 'task_2',
                    name: 'create_insight',
                    type: 'tool_call',
                    args: {
                        commentary: 'Identifying peak usage times and user segments',
                    },
                },
                {
                    id: 'task_3',
                    name: 'search',
                    type: 'tool_call',
                    args: {
                        kind: 'insights',
                    },
                },
                {
                    id: 'task_4',
                    name: 'search',
                    type: 'tool_call',
                    args: {
                        kind: 'docs',
                    },
                },
                {
                    id: 'task_5',
                    name: 'create_insight',
                    type: 'tool_call',
                    args: {},
                },
            ],
            meta: {
                thinking: [
                    {
                        thinking: 'Analyzing user engagement metrics...',
                    },
                ],
            },
        }

        // Tool call completion messages for the first two tasks
        const toolCallCompletion1 = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'task_1',
            content: 'Successfully loaded user data for the last 30 days',
            id: 'tool-completion-1',
        }

        const toolCallCompletion2 = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'task_2',
            content: 'Engagement pattern analysis completed',
            id: 'tool-completion-2',
        }

        const updateMessages = [
            {
                tool_call_id: 'task_3',
                content: 'Fetching last 30 days of user activity',
                id: 'task-exec-msg-1-1',
            },
            {
                tool_call_id: 'task_3',
                content: 'Data loaded successfully',
                id: 'task-exec-msg-1-1',
            },
            {
                tool_call_id: 'task_4',
                content: 'Processing funnel metrics across key paths',
                id: 'task-exec-msg-1-1',
            },
            {
                tool_call_id: 'task_5',
                content: 'Exploring data...',
                id: 'task-exec-msg-1-1',
            },
        ]

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: 'in_progress' })}`,
                            'event: message',
                            `data: ${JSON.stringify({ ...humanMessage, content: 'Execute analysis tasks' })}`,
                            'event: message',
                            `data: ${JSON.stringify(taskExecutionMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion1)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion2)}`,
                            'event: update',
                            `data: ${JSON.stringify(updateMessages[0])}`,
                            'event: update',
                            `data: ${JSON.stringify(updateMessages[1])}`,
                            'event: update',
                            `data: ${JSON.stringify(updateMessages[2])}`,
                            'event: update',
                            `data: ${JSON.stringify(updateMessages[3])}`,
                        ])
                    ),
            },
            get: {
                '/api/environments/:team_id/conversations/in_progress/': async () => {
                    await delay('infinite')
                    return new HttpResponse()
                },
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic: ReturnType<typeof maxThreadLogic> = maxThreadLogic({
            conversationId: 'in_progress',
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            askMax('Execute analysis tasks')
            setConversationId('in_progress')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const TaskExecutionWithFailure: Story = {
    render: () => {
        // Task execution with failure - tool calls with failed status
        const taskExecutionMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Executing analysis with some failures...',
            id: 'task-exec-fail-msg-1',
            tool_calls: [
                {
                    id: 'task_1',
                    name: 'search',
                    type: 'tool_call',
                    args: {
                        kind: 'insights',
                    },
                },
                {
                    id: 'task_2',
                    name: 'search',
                    type: 'tool_call',
                    args: {
                        kind: 'insights',
                    },
                },
                {
                    id: 'task_3',
                    name: 'create_insight',
                    type: 'tool_call',
                    args: {},
                },
                {
                    id: 'task_4',
                    name: 'create_insight',
                    type: 'tool_call',
                    args: {},
                },
                {
                    id: 'task_5',
                    name: 'create_insight',
                    type: 'tool_call',
                    args: {},
                },
            ],
        }

        // Tool call completion messages - task 1 and 2 complete, task 3 fails
        const toolCallCompletion1 = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'task_1',
            content: 'Successfully loaded user data',
            id: 'tool-completion-fail-1',
        }

        const toolCallCompletion2 = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'task_2',
            content: 'Engagement patterns analyzed',
            id: 'tool-completion-fail-2',
        }

        const toolCallCompletion3 = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'task_3',
            content: 'Failed to calculate conversion rates due to insufficient data',
            id: 'tool-completion-fail-3',
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Execute analysis with some failures',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(taskExecutionMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion1)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion2)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallCompletion3)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Execute analysis with some failures')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const MultiVisualizationInThread: Story = {
    render: () => {
        // Mock the queries endpoint to return dummy data
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/query/:kind/': () => [
                    200,
                    {
                        results: [[100, 120, 130, 140, 150]],
                        columns: ['count'],
                        types: ['integer'],
                        hogql: 'SELECT count() FROM events',
                    },
                ],
                '/api/environments/:team_id/conversations/': () => {
                    const humanMsg = {
                        type: AssistantMessageType.Human,
                        content: 'Analyze our product metrics comprehensively',
                        id: 'human-multi-viz',
                    }

                    const multiVizMessage: MultiVisualizationMessage = {
                        type: AssistantMessageType.MultiVisualization,
                        id: 'multi-viz-1',
                        visualizations: [
                            {
                                query: 'Daily Active Users',
                                plan: 'Track user engagement over the past 30 days',
                                answer: {
                                    kind: 'TrendsQuery',
                                    series: [{ event: '$pageview', name: 'Pageviews' }],
                                    dateRange: { date_from: '-30d' },
                                } as any,
                            },
                            {
                                query: 'User Conversion Funnel',
                                plan: 'Analyze conversion from signup to purchase',
                                answer: {
                                    kind: 'FunnelsQuery',
                                    series: [
                                        { event: 'user signed up' },
                                        { event: 'viewed product' },
                                        { event: 'completed purchase' },
                                    ],
                                } as any,
                            },
                            {
                                query: 'Feature Adoption',
                                plan: 'Measure feature usage rates',
                                answer: {
                                    kind: 'TrendsQuery',
                                    series: [{ event: 'feature_used', name: 'Feature Usage' }],
                                    breakdownFilter: { breakdown: 'feature_name', breakdown_type: 'event' },
                                } as any,
                            },
                        ],
                        commentary: `I've analyzed your product metrics across three key dimensions:

1. **User Engagement**: Daily active users show a positive trend with 25% growth
2. **Conversion Funnel**: 40% drop-off at payment step needs attention
3. **Feature Adoption**: New dashboard feature has 65% adoption rate

### Recommendations
- Optimize the payment flow to reduce friction
- Continue current engagement strategies
- Apply dashboard rollout strategy to future features`,
                    }

                    return new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMsg,
                                content: 'Analyze our product metrics comprehensively',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(multiVizMessage)}`,
                        ])
                    )
                },
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Analyze our product metrics comprehensively')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ThreadWithSQLQueryOverflow: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () => new HttpResponse(sqlQueryResponseChunk),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Show me a complex SQL query')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const SearchSessionRecordingsEmpty: Story = {
    render: () => {
        // This story demonstrates the search_session_recordings tool with nested filter groups
        // showcasing the fix for proper rendering of nested OR/AND groups
        const toolCallMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Let me search for those recordings...',
            id: 'search-recordings-msg',
            tool_calls: [
                {
                    id: 'search_tool_1',
                    name: 'search_session_recordings',
                    type: 'tool_call',
                    args: {},
                },
            ],
        }

        // Tool call result with nested filter groups: (Chrome AND Mac) OR (Firefox AND Windows)
        const toolCallResult: AssistantToolCallMessage = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'search_tool_1',
            content: 'Found recordings matching your criteria',
            id: 'tool-result-1',
            ui_payload: {
                search_session_recordings: {
                    date_from: '-7d',
                    date_to: null,
                    duration: [],
                    filter_group: {
                        type: FilterLogicalOperator.Or,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.Event,
                                        key: 'browser',
                                        value: 'Chrome',
                                        operator: PropertyOperator.Exact,
                                    },
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$os',
                                        value: 'Mac OS X',
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                            },
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.Event,
                                        key: 'browser',
                                        value: 'Firefox',
                                        operator: PropertyOperator.Exact,
                                    },
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$os',
                                        value: 'Windows',
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content:
                                    'Show me recordings where users are on Chrome with Mac OR Firefox with Windows',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResult)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Show me recordings where users are on Chrome with Mac OR Firefox with Windows')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const SearchSessionRecordingsWithResults: Story = {
    render: () => {
        const toolCallMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Let me search for those recordings...',
            id: 'search-recordings-with-results-msg',
            tool_calls: [
                {
                    id: 'search_tool_1',
                    name: 'search_session_recordings',
                    type: 'tool_call',
                    args: {},
                },
            ],
        }

        // Tool call result with filter for Microsoft Edge on Linux
        const toolCallResult: AssistantToolCallMessage = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'search_tool_1',
            content: 'Found 2 recordings matching your criteria',
            id: 'tool-result-with-recordings-1',
            ui_payload: {
                search_session_recordings: {
                    date_from: '-7d',
                    date_to: null,
                    duration: [],
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$browser',
                                        value: 'Microsoft Edge',
                                        operator: PropertyOperator.Exact,
                                    },
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$os',
                                        value: 'Linux',
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Show me recordings where users are on Microsoft Edge with Linux',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResult)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Show me recordings where users are on Microsoft Edge with Linux')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    const version = new URL(request.url).searchParams.get('version')
                    return [
                        200,
                        {
                            has_next: false,
                            results: recordings,
                            version,
                        },
                    ]
                },
            },
        }),
    ],
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const SearchErrorTrackingIssuesEmpty: Story = {
    render: () => {
        const toolCallMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Let me search for those error tracking issues...',
            id: 'search-errors-empty-msg',
            tool_calls: [
                {
                    id: 'search_errors_tool_1',
                    name: 'search_error_tracking_issues',
                    type: 'tool_call',
                    args: {},
                },
            ],
        }

        const toolCallResult: AssistantToolCallMessage = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'search_errors_tool_1',
            content: 'No issues found matching your criteria',
            id: 'tool-result-errors-empty',
            ui_payload: {
                search_error_tracking_issues: {
                    status: 'active',
                    search_query: 'payment',
                    date_from: '-7d',
                    date_to: null,
                    order_by: 'last_seen',
                    order_direction: 'DESC',
                    has_more: false,
                    issues: [],
                } as MaxErrorTrackingSearchResponse,
            },
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Show me active payment errors from the last week',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResult)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Show me active payment errors from the last week')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const SearchErrorTrackingIssuesWithResults: Story = {
    render: () => {
        const mockIssues: MaxErrorTrackingIssuePreview[] = [
            {
                id: 'issue-1',
                name: 'TypeError: Cannot read property of undefined',
                description: "Cannot read property 'user' of undefined at CheckoutPage.render",
                status: 'active',
                library: 'web',
                first_seen: '2025-01-10T10:00:00.000000Z',
                last_seen: '2025-01-13T14:30:00.000000Z',
                occurrences: 1247,
                users: 89,
                sessions: 156,
            },
            {
                id: 'issue-2',
                name: 'NetworkError: Failed to fetch',
                description: 'Network request failed in PaymentService.processPayment',
                status: 'active',
                library: 'web',
                first_seen: '2025-01-08T08:15:00.000000Z',
                last_seen: '2025-01-13T12:45:00.000000Z',
                occurrences: 523,
                users: 67,
                sessions: 98,
            },
            {
                id: 'issue-3',
                name: 'ValidationError: Invalid card number',
                description: 'Card validation failed for input: ****-****-****-1234',
                status: 'resolved',
                library: 'python',
                first_seen: '2025-01-05T16:20:00.000000Z',
                last_seen: '2025-01-11T09:00:00.000000Z',
                occurrences: 89,
                users: 23,
                sessions: 31,
            },
        ]

        const toolCallMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Let me search for those error tracking issues...',
            id: 'search-errors-results-msg',
            tool_calls: [
                {
                    id: 'search_errors_tool_2',
                    name: 'search_error_tracking_issues',
                    type: 'tool_call',
                    args: {},
                },
            ],
        }

        const toolCallResult: AssistantToolCallMessage = {
            type: AssistantMessageType.ToolCall,
            tool_call_id: 'search_errors_tool_2',
            content: 'Found 3 issues matching your criteria',
            id: 'tool-result-errors-with-results',
            ui_payload: {
                search_error_tracking_issues: {
                    status: null,
                    search_query: 'payment',
                    date_from: '-30d',
                    date_to: null,
                    order_by: 'occurrences',
                    order_direction: 'DESC',
                    has_more: true,
                    next_cursor: '3',
                    issues: mockIssues,
                } as MaxErrorTrackingSearchResponse,
            },
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content:
                                    'Show me all payment-related errors from the last month, sorted by occurrences',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallMessage)}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallResult)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Show me all payment-related errors from the last month, sorted by occurrences')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const DangerousOperationPendingApproval: Story = {
    render: () => {
        const toolCallMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: "I'll update that dashboard for you. This requires your approval first.",
            id: 'dangerous-op-msg',
            tool_calls: [
                {
                    id: 'dangerous_op_tool_1',
                    name: 'upsert_dashboard',
                    type: 'tool_call',
                    args: {
                        dashboard_id: 'dashboard-123',
                        tiles: [],
                    },
                },
            ],
        }

        const previewText = `This will update the dashboard "Sales Analytics Q1":

## Changes:
• Remove 3 existing tiles
• Add 2 new insight tiles
• Update dashboard filters

## Tiles to be removed:
  - Weekly Revenue (insight-456)
  - Monthly Users (insight-789)
  - Conversion Rate (insight-012)

## Tiles to be added:
  - Daily Active Users trend
  - Funnel: Signup to Purchase

**⚠️ This will modify the existing dashboard layout.**`

        // PendingApproval event - this populates pendingApprovalsData in the logic
        const pendingApproval: PendingApproval = {
            proposal_id: 'proposal-abc-123',
            decision_status: 'pending',
            tool_name: 'upsert_dashboard',
            preview: previewText,
            payload: {
                dashboard_id: 'dashboard-123',
                tiles: [],
            },
            original_tool_call_id: 'dangerous_op_tool_1',
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Update my Sales Analytics dashboard with new metrics',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallMessage)}`,
                            'event: approval',
                            `data: ${JSON.stringify(pendingApproval)}`,
                        ])
                    ),
            },
            get: {
                [`/api/environments/:team_id/conversations/${CONVERSATION_ID}/`]: () => [
                    200,
                    {
                        id: CONVERSATION_ID,
                        status: 'idle',
                        title: 'Test Conversation',
                        created_at: '2025-04-29T17:44:21.654307Z',
                        updated_at: '2025-04-29T17:44:29.184791Z',
                        user: MOCK_DEFAULT_BASIC_USER,
                        messages: [],
                        pending_approvals: [pendingApproval],
                    },
                ],
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Update my Sales Analytics dashboard with new metrics')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const DangerousOperationPendingApprovalLongContent: Story = {
    render: () => {
        const toolCallMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: "I'll perform the comprehensive migration. This requires your approval first.",
            id: 'dangerous-op-long-msg',
            tool_calls: [
                {
                    id: 'dangerous_op_tool_long_1',
                    name: 'upsert_dashboard',
                    type: 'tool_call',
                    args: {
                        dashboard_id: 'dashboard-long-preview',
                        tiles: [],
                    },
                },
            ],
        }

        const longPreviewText = `# Database Migration Plan

This migration will update **multiple tables** across the system.

## Summary

- **Total tables affected**: 15
- **Total records to migrate**: 2,453,891
- **Estimated downtime**: 0 (zero-downtime migration)
- **Rollback strategy**: Automated via migration versioning

## Phase 1: Schema Updates

### Table: users
\`\`\`sql
ALTER TABLE users ADD COLUMN preferences JSONB DEFAULT '{}';
ALTER TABLE users ADD COLUMN last_active_at TIMESTAMP;
ALTER TABLE users ADD COLUMN notification_settings JSONB;
\`\`\`

### Table: organizations
\`\`\`sql
ALTER TABLE organizations ADD COLUMN billing_tier VARCHAR(50);
ALTER TABLE organizations ADD COLUMN feature_flags JSONB DEFAULT '{}';
ALTER TABLE organizations ADD COLUMN quota_limits JSONB;
\`\`\`

### Table: projects
\`\`\`sql
ALTER TABLE projects ADD COLUMN archived_at TIMESTAMP;
ALTER TABLE projects ADD COLUMN metadata JSONB DEFAULT '{}';
\`\`\`

## Phase 2: Data Migration

The following data transformations will be applied:

1. **User preferences migration**
   - Migrate legacy \`settings\` column to new \`preferences\` JSONB
   - Parse and normalize date formats
   - Apply default values for missing fields

2. **Organization billing tier**
   - Map existing \`plan_id\` to new \`billing_tier\`
   - Free → \`starter\`
   - Pro → \`growth\`
   - Enterprise → \`scale\`

3. **Project metadata**
   - Consolidate \`extra_data\` and \`config\` into \`metadata\`
   - Remove deprecated fields

## Phase 3: Index Creation

New indexes to improve query performance:

| Table | Index Name | Columns | Type |
|-------|-----------|---------|------|
| users | idx_users_last_active | last_active_at | BTREE |
| users | idx_users_preferences | preferences | GIN |
| organizations | idx_org_billing | billing_tier | BTREE |
| projects | idx_projects_archived | archived_at | BTREE |
| events | idx_events_timestamp | timestamp, team_id | BTREE |

## Phase 4: Cleanup

After successful migration:

- Drop legacy columns: \`users.old_settings\`, \`organizations.plan_id\`
- Remove temporary migration tables
- Update materialized views

## Affected Services

The following services will need to be notified:

- ✅ API Gateway
- ✅ Event Ingestion Pipeline
- ✅ Query Engine
- ✅ Billing Service
- ✅ Notification Service
- ✅ Export Service

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Data loss | Low | High | Full backup before migration |
| Performance degradation | Medium | Medium | Run during low-traffic hours |
| Service interruption | Low | High | Blue-green deployment |
| Rollback failure | Very Low | Critical | Tested rollback procedure |

⚠️ **This is a significant operation that will modify your production database.**`

        const pendingApproval: PendingApproval = {
            proposal_id: 'proposal-long-content-123',
            decision_status: 'pending',
            tool_name: 'upsert_dashboard',
            preview: longPreviewText,
            payload: {
                dashboard_id: 'dashboard-long-preview',
                tiles: [],
            },
            original_tool_call_id: 'dangerous_op_tool_long_1',
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Run the database migration',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(toolCallMessage)}`,
                            'event: approval',
                            `data: ${JSON.stringify(pendingApproval)}`,
                        ])
                    ),
            },
            get: {
                [`/api/environments/:team_id/conversations/${CONVERSATION_ID}/`]: () => [
                    200,
                    {
                        id: CONVERSATION_ID,
                        status: 'idle',
                        title: 'Test Conversation',
                        created_at: '2025-04-29T17:44:21.654307Z',
                        updated_at: '2025-04-29T17:44:29.184791Z',
                        user: MOCK_DEFAULT_BASIC_USER,
                        messages: [],
                        pending_approvals: [pendingApproval],
                    },
                ],
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Run the database migration')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

// Notebook Artifact Stories

export const NotebookArtifactMarkdownOnly: Story = {
    render: () => {
        const notebookContent: NotebookArtifactContent = {
            content_type: ArtifactContentType.Notebook,
            title: 'User Retention Analysis',
            blocks: [
                {
                    type: 'markdown',
                    content:
                        '## User Retention Analysis\n\nThis notebook contains an analysis of user retention patterns over the last 90 days.',
                },
                {
                    type: 'markdown',
                    content:
                        '### Key Findings\n\n- Day 1 retention: **45%** of users return the next day\n- Week 1 retention: **28%** of users are still active after 7 days\n- Month 1 retention: **15%** of users remain engaged after 30 days',
                },
                {
                    type: 'markdown',
                    content:
                        '### Recommendations\n\n1. Improve onboarding completion rate\n2. Implement mobile-first features\n3. Add engagement features for the 6-9 PM window\n4. Create re-engagement campaigns for users who drop off after day 1',
                },
            ],
        }

        const notebookArtifactMessage = {
            type: AssistantMessageType.Artifact,
            artifact_id: 'notebook-markdown-1',
            source: 'artifact',
            content: notebookContent,
            id: 'notebook-artifact-msg-1',
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Create a retention analysis notebook',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookArtifactMessage)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Create a retention analysis notebook')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const NotebookArtifactWithVisualizations: Story = {
    render: () => {
        const notebookContent: NotebookArtifactContent = {
            content_type: ArtifactContentType.Notebook,
            title: 'Dashboard Analysis',
            blocks: [
                {
                    type: 'markdown',
                    content: '## Dashboard Analysis\n\nAnalyzing key product metrics.',
                },
                {
                    type: 'visualization',
                    query: {
                        kind: 'TrendsQuery',
                        series: [{ event: '$pageview', name: 'Pageviews' }],
                        dateRange: { date_from: '-30d' },
                    } as TrendsQuery,
                    title: 'Daily Active Users',
                },
                {
                    type: 'markdown',
                    content: 'The chart above shows our daily active users trend. Note the consistent growth pattern.',
                },
                {
                    type: 'visualization',
                    query: {
                        kind: 'FunnelsQuery',
                        series: [
                            { event: 'user signed up' },
                            { event: 'viewed product' },
                            { event: 'completed purchase' },
                        ],
                    } as FunnelsQuery,
                    title: 'Conversion Funnel',
                },
            ],
        }

        const notebookArtifactMessage = {
            type: AssistantMessageType.Artifact,
            artifact_id: 'notebook-viz-1',
            source: 'artifact',
            content: notebookContent,
            id: 'notebook-artifact-msg-2',
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Create a dashboard analysis notebook with charts',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookArtifactMessage)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Create a dashboard analysis notebook with charts')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const NotebookArtifactMixedContent: Story = {
    render: () => {
        const notebookContent: NotebookArtifactContent = {
            content_type: ArtifactContentType.Notebook,
            title: 'Complete Product Analysis',
            blocks: [
                {
                    type: 'markdown',
                    content:
                        '# Complete Product Analysis\n\nThis comprehensive notebook covers user behavior, funnel analysis, and session replays.',
                },
                {
                    type: 'markdown',
                    content: '## 1. User Engagement Trends',
                },
                {
                    type: 'visualization',
                    query: {
                        kind: 'TrendsQuery',
                        series: [{ event: '$pageview', name: 'Page Views' }],
                        dateRange: { date_from: '-30d' },
                    } as TrendsQuery,
                    title: 'User Engagement',
                },
                {
                    type: 'markdown',
                    content: '## 2. Conversion Funnel\n\nOur main conversion funnel from signup to purchase:',
                },
                {
                    type: 'visualization',
                    query: {
                        kind: 'FunnelsQuery',
                        series: [
                            { event: 'user signed up' },
                            { event: 'added to cart' },
                            { event: 'completed purchase' },
                        ],
                    } as FunnelsQuery,
                    title: 'Purchase Funnel',
                },
                {
                    type: 'markdown',
                    content:
                        '## 3. User Session Analysis\n\nHere is an example session showing a user completing the checkout flow:',
                },
                {
                    type: 'session_replay',
                    session_id: 'session-abc123',
                    timestamp_ms: 1704067200000,
                    title: 'Checkout Flow Example',
                },
                {
                    type: 'markdown',
                    content:
                        '## Conclusions\n\n- User engagement is growing steadily\n- The checkout funnel has a 15% drop-off at the payment step\n- Session replays reveal UX friction in the cart page',
                },
            ],
        }

        const notebookArtifactMessage = {
            type: AssistantMessageType.Artifact,
            artifact_id: 'notebook-mixed-1',
            source: 'artifact',
            content: notebookContent,
            id: 'notebook-artifact-msg-3',
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Create a comprehensive product analysis notebook',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookArtifactMessage)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Create a comprehensive product analysis notebook')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const NotebookArtifactWithLoadingAndErrors: Story = {
    render: () => {
        const notebookContent: NotebookArtifactContent = {
            content_type: ArtifactContentType.Notebook,
            title: 'Analysis with Loading States',
            blocks: [
                {
                    type: 'markdown',
                    content: '# Analysis with Loading States\n\nThis notebook demonstrates loading and error states.',
                },
                {
                    type: 'visualization',
                    query: {
                        kind: 'TrendsQuery',
                        series: [{ event: '$pageview', name: 'Page Views' }],
                        dateRange: { date_from: '-7d' },
                    } as TrendsQuery,
                    title: 'Successfully Loaded Chart',
                },
                {
                    type: 'markdown',
                    content: '## Pending Visualization\n\nThe following chart is still loading:',
                },
                {
                    type: 'loading',
                    artifact_id: 'pending-viz-123',
                },
                {
                    type: 'markdown',
                    content: '## Missing Visualization\n\nThe following chart could not be found:',
                },
                {
                    type: 'error',
                    message: 'Visualization not found: missing-artifact-456',
                    artifact_id: 'missing-artifact-456',
                },
                {
                    type: 'markdown',
                    content: '## Conclusions\n\nThis demonstrates how the notebook handles different block states.',
                },
            ],
        }

        const notebookArtifactMessage = {
            type: AssistantMessageType.Artifact,
            artifact_id: 'notebook-loading-errors-1',
            source: 'artifact',
            content: notebookContent,
            id: 'notebook-artifact-msg-loading-errors',
        }

        useStorybookMocks({
            post: {
                '/api/environments/:team_id/conversations/': () =>
                    new HttpResponse(
                        generateChunk([
                            'event: conversation',
                            `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
                            'event: message',
                            `data: ${JSON.stringify({
                                ...humanMessage,
                                content: 'Show me an analysis with loading and error states',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(notebookArtifactMessage)}`,
                        ])
                    ),
            },
        })

        const { setConversationId } = useActions(maxLogic({ panelId: 'storybook' }))
        const threadLogic = maxThreadLogic({
            conversationId: CONVERSATION_ID,
            conversation: null,
            panelId: 'storybook',
        })
        const { askMax } = useActions(threadLogic)
        const { dataProcessingAccepted } = useValues(maxGlobalLogic)

        useAutoSendOnce(CONVERSATION_ID, dataProcessingAccepted, () => {
            setConversationId(CONVERSATION_ID)
            askMax('Show me an analysis with loading and error states')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

// Changelog Stories

const SAMPLE_CHANGELOG_ENTRIES: ChangelogEntry[] = [
    {
        title: 'SQL generation',
        description: 'Max can now write and run SQL queries for you',
        tag: 'new',
    },
    {
        title: 'Faster responses',
        description: 'Improved response times by up to 40%',
        tag: 'improved',
    },
    {
        title: 'Chart editing',
        description: 'Edit visualization settings directly in conversation',
        tag: 'beta',
    },
]

export const ChangelogOnly: Story = {
    render: () => {
        const { setEntries, openChangelog } = useActions(maxChangelogLogic)

        useEffect(() => {
            setEntries(SAMPLE_CHANGELOG_ENTRIES)
            setTimeout(() => openChangelog(), 100)
        }, [setEntries, openChangelog])

        return <Template />
    },
    parameters: {
        featureFlags: ['posthog-ai-changelog'],
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}
