import { MOCK_DEFAULT_BASIC_USER } from '~/lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import type {
    UserInterviewSearchResultApi,
    UserInterviewTopicApi,
} from '../../../../products/user_interviews/frontend/generated/api.schemas'

const MOCK_TOPICS = [
    {
        id: '01999999-0000-0000-0000-000000000001',
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2026-05-15T10:00:00Z',
        topic: 'How users discover the MCP integration',
        interviewee_emails: ['alex@example.com', 'sam@example.com', 'jordan@example.com', 'taylor@example.com'],
        interviewee_distinct_ids: [],
        agent_context: '',
        questions: ['Why MCP?', 'Web UI experience?', 'What could we improve?'],
    },
    {
        id: '01999999-0000-0000-0000-000000000002',
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2026-05-12T09:30:00Z',
        topic: 'Trial users that did not convert',
        interviewee_emails: ['paul@example.com', 'jane@example.com'],
        interviewee_distinct_ids: ['distinct-no-email'],
        agent_context: 'Be warm, the trial just ended',
        questions: ['What was missing?', 'What were you hoping for?'],
    },
    {
        id: '01999999-0000-0000-0000-000000000003',
        created_by: MOCK_DEFAULT_BASIC_USER,
        created_at: '2026-05-10T14:00:00Z',
        topic: 'Power users of session replay',
        interviewee_emails: [],
        interviewee_distinct_ids: ['power-user-1', 'power-user-2'],
        agent_context: '',
        questions: ['How did you discover replay?', 'What workflow does it support?'],
    },
] as unknown as UserInterviewTopicApi[]

const MOCK_SEARCH_RESULTS: UserInterviewSearchResultApi[] = [
    {
        interview_id: 'i-1',
        topic_id: '01999999-0000-0000-0000-000000000001',
        document_type: 'transcript',
        similarity: 0.92,
        interviewee_identifier: 'alex@example.com',
        content_snippet:
            "I just use the MCP from Claude Code. Honestly I've never opened the PostHog web UI to make a chart — the agent does it faster and I trust it.",
        created_at: '2026-05-12T10:00:00Z',
    },
    {
        interview_id: 'i-2',
        topic_id: '01999999-0000-0000-0000-000000000001',
        document_type: 'summary',
        similarity: 0.84,
        interviewee_identifier: 'sam@example.com',
        content_snippet:
            'Heavy MCP user. Prefers conversational queries over clicking through filters. Wants chart-saving via the MCP to be more obvious.',
        created_at: '2026-05-11T09:30:00Z',
    },
    {
        interview_id: 'i-3',
        topic_id: '01999999-0000-0000-0000-000000000001',
        document_type: 'transcript',
        similarity: 0.71,
        interviewee_identifier: 'taylor@example.com',
        content_snippet:
            "Most of my colleagues still use the web UI, but I'm a CLI person. The MCP fits my workflow because I'm already in my terminal all day.",
        created_at: '2026-05-10T16:00:00Z',
    },
]

type Empty = Record<string, never>

const meta: Meta<Empty> = {
    component: App,
    title: 'Scenes-App/User Research/Topics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-19',
        pageUrl: urls.userInterviews(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/user_interview_topics/': toPaginatedResponse(MOCK_TOPICS),
            },
            post: {
                '/api/environments/:team_id/user_interviews/search/': MOCK_SEARCH_RESULTS,
            },
        }),
    ],
}
export default meta
type Story = StoryObj<Empty>

async function typeSearch(canvasElement: HTMLElement, query: string): Promise<void> {
    const canvas = within(canvasElement)
    const input = await canvas.findByPlaceholderText(/Search what users said/i)
    await userEvent.type(input, query)
}

export const TopicsList: Story = {}

export const SearchWithResults: Story = {
    play: async ({ canvasElement }) => {
        await typeSearch(canvasElement, 'how do you use the mcp')
    },
}

export const SearchNoResults: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/user_interview_topics/': toPaginatedResponse(MOCK_TOPICS),
            },
            post: {
                '/api/environments/:team_id/user_interviews/search/': [] as UserInterviewSearchResultApi[],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await typeSearch(canvasElement, 'something nobody talked about')
    },
}
