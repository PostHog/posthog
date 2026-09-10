import { CONVERSATION_ID, humanMessage } from './__mocks__/chatResponse.mocks'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { HttpResponse } from 'msw'

import { useStorybookMocks } from '~/mocks/browser'
import {
    AssistantMessage,
    AssistantMessageType,
    MultiQuestionFormQuestion,
} from '~/queries/schema/schema-assistant-messages'

import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { Template, generateChunk, sharedMeta, useAutoSendOnce } from './maxStoriesShared'
import { maxThreadLogic } from './maxThreadLogic'

const meta: Meta = {
    title: 'Scenes-App/PostHog AI/Forms',
    ...sharedMeta,
}
export default meta

type Story = StoryObj<{}>

export const ThreadWithMultiQuestionForm: Story = {
    render: () => {
        // Multi-question form with several questions - uses tool_calls format
        const formQuestions: MultiQuestionFormQuestion[] = [
            {
                id: 'use_case',
                title: 'Use case',
                question: 'What is your primary use case for PostHog?',
                options: [
                    { value: 'Product Analytics', description: 'Track your product metrics and KPIs' },
                    {
                        value: 'A/B Testing',
                        description: 'Test different versions of your product to see which one performs better',
                    },
                    {
                        value: 'Session Replay',
                        description:
                            'Record and replay user sessions to understand how they interact with your product',
                    },
                    { value: 'User Surveys', description: 'Collect feedback from your users to improve your product' },
                ],
                allow_custom_answer: true,
            },
            {
                id: 'team_size',
                question: 'How large is your team?',
                title: 'Team size',
                options: [
                    { value: 'Just me', description: 'I work alone on my product' },
                    { value: '2-10 people', description: 'I have a small team working on my product' },
                    { value: '11-50 people', description: 'I have a medium-sized team working on my product' },
                    { value: '50+ people', description: 'I have a large team working on my product' },
                ],
                allow_custom_answer: false,
            },
            {
                id: 'experience',
                title: 'Experience',
                question: 'How familiar are you with analytics tools?',
                options: [
                    { value: 'Beginner', description: 'I have no experience with analytics tools' },
                    { value: 'Intermediate', description: 'I have some experience with analytics tools' },
                    { value: 'Expert', description: 'I have a lot of experience with analytics tools' },
                ],
            },
        ]

        const multiQuestionFormMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'To help you better, I need to understand your needs. Please answer these quick questions:',
            id: 'multi-question-form-msg',
            tool_calls: [
                {
                    id: 'create-form-tool-call-1',
                    name: 'create_form',
                    args: { questions: formQuestions },
                    type: 'tool_call',
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
                                content: 'Help me get started with PostHog',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(multiQuestionFormMessage)}`,
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
            askMax('Help me get started with PostHog')
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

export const ThreadWithMultiFieldQuestion: Story = {
    render: () => {
        const formQuestions: MultiQuestionFormQuestion[] = [
            {
                id: 'experiment_config',
                title: 'Config',
                question: 'Configure your experiment',
                fields: [
                    {
                        id: 'min_sample',
                        type: 'number',
                        label: 'Minimum sample size',
                        min: 100,
                        max: 100000,
                        placeholder: 'e.g. 1000',
                    },
                    { id: 'confidence', type: 'slider', label: 'Confidence level (%)', min: 80, max: 99, step: 1 },
                    { id: 'notify_on_completion', type: 'toggle', label: 'Notify me when complete' },
                ],
            },
            {
                id: 'metric_type',
                title: 'Metric',
                question: 'What type of metric are you testing?',
                options: [
                    { value: 'Conversion rate', description: 'Percentage of users who complete a goal' },
                    { value: 'Revenue per user', description: 'Average revenue generated per user' },
                    { value: 'Engagement score', description: 'Composite metric of user activity' },
                ],
            },
        ]

        const multiQuestionFormMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: "Let's set up your experiment. Please configure the settings below:",
            id: 'multi-field-form-msg',
            tool_calls: [
                {
                    id: 'create-form-multi-field',
                    name: 'create_form',
                    args: { questions: formQuestions },
                    type: 'tool_call',
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
                                content: 'Help me set up an A/B test',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(multiQuestionFormMessage)}`,
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
            askMax('Help me set up an A/B test')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ThreadWithSingleQuestionForm: Story = {
    render: () => {
        // Single question form - uses tool_calls format
        const formQuestions: MultiQuestionFormQuestion[] = [
            {
                id: 'data_volume',
                title: 'Data volume',
                question: 'What is your approximate monthly event volume?',
                options: [
                    { value: 'Under 1 million events' },
                    { value: '1-10 million events' },
                    { value: '10-100 million events' },
                    { value: 'Over 100 million events' },
                ],
                allow_custom_answer: true,
            },
        ]

        const singleQuestionFormMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Before I proceed, I need to know:',
            id: 'single-question-form-msg',
            tool_calls: [
                {
                    id: 'create-form-tool-call-2',
                    name: 'create_form',
                    args: { questions: formQuestions },
                    type: 'tool_call',
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
                                content: 'What pricing plan should I choose?',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(singleQuestionFormMessage)}`,
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
            askMax('What pricing plan should I choose?')
        })

        if (!dataProcessingAccepted) {
            return <></>
        }

        return <Template />
    },
}

export const ThreadWithMultiQuestionFormLongContent: Story = {
    render: () => {
        // Form with long questions and answers - agent asking for confirmation before research
        const formQuestions = [
            {
                id: 'research_scope',
                title: 'Research scope',
                question:
                    'I found multiple potential areas to investigate regarding your user retention issues. Which aspect should I prioritize in my analysis?',
                options: [
                    {
                        value: 'Onboarding',
                        description:
                            'Onboarding flow completion rates and drop-off points across different user segments',
                    },
                    {
                        value: 'Feature adoption',
                        description: 'Feature adoption patterns and correlation with long-term retention metrics',
                    },
                    {
                        value: 'User engagement',
                        description:
                            'User engagement frequency analysis including session duration and return visit patterns',
                    },
                    {
                        value: 'Cohort',
                        description: 'Cohort-based comparison of retained vs churned users over the past 6 months',
                    },
                ],
                allow_custom_answer: true,
            },
            {
                id: 'data_timeframe',
                title: 'Data timeframe',
                question:
                    'What time period should I focus on for this analysis? Longer periods provide more data but may include outdated patterns, while shorter periods give more recent insights but with less statistical significance.',
                options: [
                    { value: 'Last 30 days', description: 'Most recent data, best for identifying current issues' },
                    { value: 'Last 90 days', description: 'Good balance of recency and data volume' },
                    { value: 'Last 6 months', description: 'Comprehensive view including seasonal variations' },
                    { value: 'Last 12 months', description: 'Full year analysis for long-term trend identification' },
                ],
                allow_custom_answer: false,
            },
            {
                id: 'user_segment',
                title: 'User segment',
                question:
                    'Should I focus on a specific user segment, or analyze all users? Focusing on a segment can provide more actionable insights for that group, while analyzing all users gives a broader picture.',
                options: [
                    { value: 'All users', description: 'Comprehensive analysis across the entire user base' },
                    { value: 'New users', description: 'Focus on early retention' },
                    { value: 'Power users', description: 'Understand what keeps engaged users' },
                    { value: 'At-risk users', description: 'Identify churn prevention opportunities' },
                ],
                allow_custom_answer: true,
            },
            {
                id: 'output_format',
                title: 'Output format',
                question:
                    'How would you like me to present the findings? I can create different types of deliverables depending on your needs and who will be reviewing the results.',
                options: [
                    {
                        value: 'Executive summary',
                        description:
                            'Executive summary with key findings and recommended actions (best for stakeholder presentations)',
                    },
                    {
                        value: 'Detailed analytical report',
                        description:
                            'Detailed analytical report with methodology, data tables, and statistical analysis',
                    },
                    {
                        value: 'Interactive dashboard',
                        description: 'Interactive dashboard with visualizations that you can explore and filter',
                    },
                    {
                        value: 'Prioritized list of action items',
                        description:
                            'Prioritized list of action items with expected impact and implementation complexity',
                    },
                ],
                allow_custom_answer: true,
            },
        ]

        const longContentFormMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content:
                "I've analyzed your request and identified several areas that need investigation. Before I proceed with the research, I need to confirm a few things to ensure I focus on what matters most to you.",
            id: 'long-content-form-msg',
            tool_calls: [
                {
                    id: 'create-form-tool-call-3',
                    name: 'create_form',
                    args: { questions: formQuestions },
                    type: 'tool_call',
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
                                content:
                                    'Can you help me understand why our user retention has been declining? I need a comprehensive analysis.',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(longContentFormMessage)}`,
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
            askMax(
                'Can you help me understand why our user retention has been declining? I need a comprehensive analysis.'
            )
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

export const ThreadWithMultiQuestionFormNoCustomAnswer: Story = {
    render: () => {
        // Form without custom answer options - uses tool_calls format
        const formQuestions: MultiQuestionFormQuestion[] = [
            {
                id: 'priority',
                question: 'What is your top priority right now?',
                title: 'Priority',
                options: [
                    { value: 'Growing user base' },
                    { value: 'Improving retention' },
                    { value: 'Increasing conversion' },
                    { value: 'Boosting engagement' },
                ],
                allow_custom_answer: false,
            },
            {
                id: 'focus_areas',
                question: 'Which areas should I cover?',
                title: 'Focus',
                type: 'multi_select',
                options: [{ value: 'Acquisition' }, { value: 'Engagement' }, { value: 'Retention' }],
                allow_custom_answer: false,
            },
            {
                id: 'timeline',
                question: 'What is your timeline?',
                title: 'Timeline',
                options: [{ value: 'This week' }, { value: 'This month' }, { value: 'This quarter' }],
                allow_custom_answer: false,
            },
        ]

        const formMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Please select from the following options:',
            id: 'no-custom-form-msg',
            tool_calls: [
                {
                    id: 'create-form-tool-call-4',
                    name: 'create_form',
                    args: { questions: formQuestions },
                    type: 'tool_call',
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
                                content: 'Help me prioritize my analytics work',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(formMessage)}`,
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
            askMax('Help me prioritize my analytics work')
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

// Multi-question form stories with new field types

export const ThreadWithMixedFieldTypeForm: Story = {
    render: () => {
        const formQuestions: MultiQuestionFormQuestion[] = [
            {
                id: 'goal',
                title: 'Goal',
                question: 'What is your primary goal for this analysis?',
                type: 'select',
                options: [
                    { value: 'Understand user behavior', description: 'See how users interact with your product' },
                    { value: 'Measure conversion', description: 'Track how users move through a funnel' },
                    { value: 'Compare segments', description: 'Analyze differences between user groups' },
                ],
            },
            {
                id: 'features',
                title: 'Features',
                type: 'multi_select',
                question: 'Which analytics features are you interested in?',
                options: [
                    { value: 'Funnels', description: 'Track conversion through steps' },
                    { value: 'Retention', description: 'Measure user stickiness over time' },
                    { value: 'Paths', description: 'Visualize user navigation flows' },
                    { value: 'Trends', description: 'Monitor metrics over time' },
                ],
            },
            {
                id: 'config',
                title: 'Config',
                type: 'multi_field',
                question: 'A few more details',
                fields: [
                    {
                        id: 'team_size',
                        type: 'slider',
                        label: 'How many people are on your team?',
                        min: 1,
                        max: 100,
                        step: 1,
                    },
                    { id: 'notify', type: 'toggle', label: 'Would you like weekly email reports?' },
                ],
            },
        ]

        const multiQuestionFormMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Let me tailor your experience. Please answer these quick questions:',
            id: 'mixed-form-msg',
            tool_calls: [
                {
                    id: 'create-form-mixed-1',
                    name: 'create_form',
                    args: { questions: formQuestions },
                    type: 'tool_call',
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
                                content: 'Help me set up analytics for my team',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(multiQuestionFormMessage)}`,
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
            askMax('Help me set up analytics for my team')
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

export const ThreadWithTextAndNumberForm: Story = {
    render: () => {
        const formQuestions: MultiQuestionFormQuestion[] = [
            {
                id: 'project_details',
                title: 'Details',
                type: 'multi_field',
                question: 'Tell me about your project',
                fields: [
                    { id: 'project_name', type: 'text', label: 'Project name', placeholder: 'e.g. My SaaS App' },
                    {
                        id: 'monthly_events',
                        type: 'number',
                        label: 'Expected monthly events',
                        placeholder: 'e.g. 500000',
                        min: 0,
                        max: 100000000,
                        step: 1000,
                    },
                    {
                        id: 'data_source',
                        type: 'dropdown',
                        label: 'Primary data source',
                        options: [
                            { value: 'Web app', description: 'JavaScript/React/Vue application' },
                            { value: 'Mobile app', description: 'iOS or Android application' },
                            { value: 'Backend', description: 'Server-side events via API' },
                            { value: 'Third-party', description: 'Import from another analytics tool' },
                        ],
                    },
                ],
            },
        ]

        const multiQuestionFormMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: "I'd like to learn more about your project to give you the best recommendations:",
            id: 'text-number-form-msg',
            tool_calls: [
                {
                    id: 'create-form-text-number-1',
                    name: 'create_form',
                    args: { questions: formQuestions },
                    type: 'tool_call',
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
                                content: 'I want to set up event tracking for my project',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(multiQuestionFormMessage)}`,
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
            askMax('I want to set up event tracking for my project')
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

export const ThreadWithSliderForm: Story = {
    render: () => {
        const formQuestions: MultiQuestionFormQuestion[] = [
            {
                id: 'experiment_config',
                title: 'Config',
                type: 'multi_field',
                question: 'Configure your experiment parameters',
                fields: [
                    { id: 'confidence', type: 'slider', label: 'Confidence level (%)', min: 80, max: 99, step: 1 },
                    { id: 'duration', type: 'slider', label: 'Duration (days)', min: 7, max: 90, step: 7 },
                    { id: 'enable_holdout', type: 'toggle', label: 'Create a holdout group' },
                ],
            },
        ]

        const multiQuestionFormMessage: AssistantMessage = {
            type: AssistantMessageType.Assistant,
            content: 'Let me configure your experiment parameters:',
            id: 'slider-form-msg',
            tool_calls: [
                {
                    id: 'create-form-slider-1',
                    name: 'create_form',
                    args: { questions: formQuestions },
                    type: 'tool_call',
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
                                content: 'Help me set up an A/B test experiment',
                            })}`,
                            'event: message',
                            `data: ${JSON.stringify(multiQuestionFormMessage)}`,
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
            askMax('Help me set up an A/B test experiment')
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
