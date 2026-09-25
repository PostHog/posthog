import { MOCK_DEFAULT_BASIC_USER } from '~/lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { ActivityScope, UserBasicType } from '~/types'

import { LLMPrompt } from './types'

const MOCK_SECOND_USER: UserBasicType = {
    id: 179,
    uuid: '018daf23-0000-0000-0000-000000000002',
    distinct_id: 'mock-user-179-distinct-id',
    first_name: 'Jane',
    email: 'jane.smith@posthog.com',
}

function createMockPrompt(overrides: Partial<LLMPrompt> & { name: string }): LLMPrompt {
    return {
        id: `prompt-${overrides.name}`,
        prompt: `You are a helpful assistant for ${overrides.name}.`,
        version: 1,
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-15T10:00:00Z',
        updated_at: '2025-01-15T10:00:00Z',
        deleted: false,
        is_latest: true,
        latest_version: 1,
        version_count: 1,
        first_version_created_at: '2025-01-15T10:00:00Z',
        activity_item_id: overrides.name,
        version_description: null,
        outline: [],
        ...overrides,
    }
}

const MOCK_PROMPTS: LLMPrompt[] = [
    createMockPrompt({
        name: 'customer-support-agent',
        prompt: 'You are a customer support agent. Be helpful, empathetic, and resolve issues quickly.',
        version: 3,
        latest_version: 3,
        version_count: 3,
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-20T14:30:00Z',
    }),
    createMockPrompt({
        name: 'code-review-assistant',
        prompt: 'You are a code reviewer. Focus on correctness, readability, and performance.',
        version: 5,
        latest_version: 5,
        version_count: 5,
        created_by: MOCK_SECOND_USER,
        created_at: '2025-01-18T09:15:00Z',
    }),
    createMockPrompt({
        name: 'summarizer',
        prompt: 'Summarize the given text concisely while retaining all key information.',
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2025-01-10T16:45:00Z',
    }),
    createMockPrompt({
        name: 'data-analyst',
        prompt: 'You are a data analyst. Interpret metrics, identify trends, and provide actionable insights.',
        version: 2,
        latest_version: 2,
        version_count: 2,
        created_by: MOCK_SECOND_USER,
        created_at: '2025-01-05T11:00:00Z',
    }),
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AI observability/Prompts',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-28',
        pageUrl: urls.aiObservabilityPrompts(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/llm_prompts/': toPaginatedResponse(MOCK_PROMPTS),
            },
        }),
    ],
}
export default meta
type Story = StoryObj<{}>

export const PromptsList: Story = {}

export const History: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityPrompts()}?tab=history`,
        featureFlags: [FEATURE_FLAGS.AUDIT_LOGS_ACCESS],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/activity_log': {
                    results: [
                        {
                            id: 'activity-003',
                            user: MOCK_SECOND_USER,
                            activity: 'updated',
                            created_at: '2025-01-27T15:00:00Z',
                            scope: ActivityScope.LLM_PROMPT_LABEL,
                            item_id: 'customer-support-agent',
                            detail: {
                                name: 'customer-support-agent: production',
                                changes: [
                                    {
                                        type: 'LLMPromptLabel',
                                        action: 'changed',
                                        field: 'version',
                                        before: 2,
                                        after: 3,
                                    },
                                ],
                            },
                        },
                        {
                            id: 'activity-002',
                            user: MOCK_DEFAULT_BASIC_USER,
                            activity: 'published',
                            created_at: '2025-01-27T14:00:00Z',
                            scope: ActivityScope.LLM_PROMPT,
                            item_id: 'customer-support-agent',
                            detail: {
                                name: 'customer-support-agent',
                                changes: [{ type: 'LLMPrompt', action: 'created', field: 'version', after: 3 }],
                            },
                        },
                        {
                            id: 'activity-001',
                            user: MOCK_SECOND_USER,
                            activity: 'published',
                            created_at: '2025-01-26T09:00:00Z',
                            scope: ActivityScope.LLM_PROMPT,
                            item_id: 'code-review-assistant',
                            detail: {
                                name: 'code-review-assistant',
                                changes: [{ type: 'LLMPrompt', action: 'created', field: 'version', after: 5 }],
                            },
                        },
                    ],
                    total_count: 3,
                },
            },
        }),
    ],
}

export const EmptyState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/llm_prompts/': toPaginatedResponse([]),
            },
        }),
    ],
}
