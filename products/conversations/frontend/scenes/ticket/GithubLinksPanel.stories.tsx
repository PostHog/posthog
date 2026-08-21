import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { TicketGithubLinkApi } from '../../generated/api.schemas'
import { GithubLinksPanel } from './GithubLinksPanel'

const TICKET_ID = '019f9582-93e7-77c1-8912-4f541d70cb13'

const LINKS: TicketGithubLinkApi[] = [
    {
        id: '019f9582-93e7-77c1-8912-4f541d70cb14',
        repo: 'PostHog/posthog',
        number: 73646,
        link_type: 'pull_request',
        url: 'https://github.com/PostHog/posthog/pull/73646',
        title: 'perf(agent): cut latency on formatting-only edits',
        link_state: 'merged',
        created_by: null,
        created_at: '2026-07-25T10:00:00Z',
    },
    {
        id: '019f9582-93e7-77c1-8912-4f541d70cb15',
        repo: 'PostHog/posthog-js',
        number: 1234,
        link_type: 'issue',
        url: 'https://github.com/PostHog/posthog-js/issues/1234',
        title: 'Session replay stops recording after route change in Next.js app router',
        link_state: 'open',
        created_by: null,
        created_at: '2026-07-25T11:00:00Z',
    },
    {
        id: '019f9582-93e7-77c1-8912-4f541d70cb16',
        repo: 'example-org/private-repo',
        number: 9,
        link_type: 'issue',
        url: 'https://github.com/example-org/private-repo/issues/9',
        title: null,
        link_state: null,
        created_by: null,
        created_at: '2026-07-25T12:00:00Z',
    },
]

const meta: Meta<typeof GithubLinksPanel> = {
    title: 'Scenes-App/Support/GithubLinksPanel',
    component: GithubLinksPanel,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-07-25' },
    decorators: [
        (Story): JSX.Element => (
            <div className="max-w-sm">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof GithubLinksPanel>

export const WithLinks: Story = {
    decorators: [
        mswDecorator({
            get: { [`/api/projects/:team_id/conversations/tickets/${TICKET_ID}/github_links/`]: LINKS },
        }),
    ],
    args: { ticketId: TICKET_ID },
}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: { [`/api/projects/:team_id/conversations/tickets/${TICKET_ID}/github_links/`]: [] },
        }),
    ],
    args: { ticketId: TICKET_ID },
}

export const ReadOnly: Story = {
    decorators: [
        mswDecorator({
            get: { [`/api/projects/:team_id/conversations/tickets/${TICKET_ID}/github_links/`]: LINKS },
        }),
    ],
    args: { ticketId: TICKET_ID, disabledReason: "You don't have edit access to this ticket" },
}
