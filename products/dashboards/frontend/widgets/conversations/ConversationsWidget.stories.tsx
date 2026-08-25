import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { DashboardPlacement } from '~/types'

import { WidgetCard } from '../../components/WidgetCard/WidgetCard'
import { WidgetCardBody } from '../../components/WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../../components/WidgetCard/WidgetCardHeader'
import {
    mockMoreOverlay,
    withConversationsProjectState,
    widgetStorybookParameters,
    widgetTileFrameDecorator,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { WidgetRuntimeAvailabilityGuard } from '../../components/WidgetRuntimeAvailabilityGuard/WidgetRuntimeAvailabilityGuard'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { useWidgetAvailability } from '../../widget_types/widgetAvailability'
import type { DashboardWidgetComponentProps } from '../registry'
import {
    ConversationsWidget,
    ConversationsWidgetTopHeading,
    type ConversationsWidgetTicket,
} from './ConversationsWidget'
import { ConversationsWidgetTileFilters } from './ConversationsWidgetTileFilters'

const CATALOG = getDashboardWidgetCatalogEntry('conversations_recent_tickets')!
const DEFAULT_CONFIG = CATALOG.defaultConfig as Record<string, unknown>
const savedViewsApiDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/conversations/views/': () => [
            200,
            {
                count: 3,
                results: [
                    { short_id: 'urgent-unassigned', name: 'Urgent and unassigned' },
                    { short_id: 'needs-reply', name: 'Needs a reply' },
                    { short_id: 'breached-sla', name: 'Breached SLA' },
                ],
            },
        ],
    },
})

function StoryTile(props: DashboardWidgetComponentProps): JSX.Element {
    const { isAvailable } = useWidgetAvailability(CATALOG.availability)
    const [config, setConfig] = useState(props.config)

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={CATALOG.headerLayout}
                title=""
                defaultTitle={CATALOG.headerTitle ?? CATALOG.label}
                titleHref={CATALOG.titleHref}
                widgetTypeLabel={getDashboardWidgetGroupLabel(CATALOG.groupId)}
                config={config}
                headerMeta={CATALOG.headerMeta}
                TopHeading={ConversationsWidgetTopHeading}
                description={CATALOG.description}
                showDescription
                loading={props.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {isAvailable ? (
                <ConversationsWidgetTileFilters tileId={props.tileId} config={config} onUpdateConfig={setConfig} />
            ) : null}
            <WidgetCardBody>
                <WidgetRuntimeAvailabilityGuard availability={CATALOG.availability}>
                    <ConversationsWidget {...props} config={config} />
                </WidgetRuntimeAvailabilityGuard>
            </WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof StoryTile> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Support/Recent tickets',
    component: StoryTile,
    parameters: { layout: 'padded', ...widgetStorybookParameters },
    decorators: [savedViewsApiDecorator, ...widgetTileFrameDecorator],
    args: {
        tileId: 1,
        config: DEFAULT_CONFIG,
        loading: false,
        result: null,
        onUpdateConfig: () => undefined,
        onRefresh: () => undefined,
    },
}
export default meta
type Story = StoryObj<typeof StoryTile>
const tickets: ConversationsWidgetTicket[] = [
    {
        id: 'ticket-1',
        ticket_number: 124,
        channel_source: 'email',
        status: 'new',
        priority: 'critical',
        assignee: null,
        updated_at: '2026-05-26T13:58:00Z',
        last_message_text:
            "I can't invite a teammate to our project. The invite link opens, but the page returns to the project settings without adding them.",
        unread_team_count: 1,
        email_subject: null,
        requester_name: 'Jordan Lee',
        requester_email: 'jordan@example.com',
        sla_due_at: '2026-05-26T14:30:00Z',
    },
    {
        id: 'ticket-2',
        ticket_number: 123,
        channel_source: 'slack',
        status: 'open',
        priority: 'high',
        assignee: { user: null, role: { id: 'role-support', name: 'Support team' } },
        updated_at: '2026-05-26T09:15:00Z',
        last_message_text: 'Thanks, that restored the dashboard.',
        unread_team_count: 0,
        email_subject: null,
        requester_name: 'Morgan Chen',
        requester_email: 'morgan@example.com',
        sla_due_at: '2026-05-26T13:30:00Z',
    },
    {
        id: 'ticket-3',
        ticket_number: 121,
        channel_source: 'widget',
        status: 'pending',
        priority: 'medium',
        assignee: null,
        updated_at: '2026-05-25T14:00:00Z',
        last_message_text: 'The Android SDK reports duplicate screen views',
        unread_team_count: 1,
        email_subject: null,
        requester_name: null,
        requester_email: 'casey@example.com',
        sla_due_at: '2026-05-28T10:00:00Z',
    },
    {
        id: 'ticket-4',
        ticket_number: 119,
        channel_source: 'email',
        status: 'resolved',
        priority: 'low',
        assignee: { user: { id: 2, name: 'Alex Kim' }, role: null },
        updated_at: '2026-05-24T18:30:00Z',
        last_message_text: 'That fixed the authorized domain. Thank you!',
        unread_team_count: 0,
        email_subject: 'Update the authorized domain',
        requester_name: 'Taylor Brooks',
        requester_email: 'taylor@example.com',
        sla_due_at: null,
    },
    {
        id: 'ticket-5',
        ticket_number: 118,
        channel_source: 'widget',
        status: 'open',
        priority: 'low',
        assignee: { user: { id: 2, name: 'Alex Kim' }, role: null },
        updated_at: '2026-05-25T11:20:00Z',
        last_message_text:
            'We are still evaluating the new billing flow. Can you explain how usage limits apply when several teams send events to the same project?',
        unread_team_count: 2,
        email_subject: 'Question about usage limits',
        requester_name: 'Pat Garcia',
        requester_email: 'pat@example.com',
        sla_due_at: '2026-05-28T10:00:00Z',
    },
    {
        id: 'ticket-6',
        ticket_number: 117,
        channel_source: 'email',
        status: 'on_hold',
        priority: 'medium',
        assignee: { user: null, role: { id: 'role-support', name: 'Support team' } },
        updated_at: '2026-05-24T18:30:00Z',
        last_message_text: "We'll review the export and follow up.",
        unread_team_count: 0,
        email_subject: 'Requested audit log export',
        requester_name: 'Robin Patel',
        requester_email: 'robin@example.com',
        sla_due_at: null,
    },
]
export const Populated: Story = {
    decorators: [withConversationsProjectState(true)],
    args: { canMutateConversationsTickets: true, result: { results: tickets, hasMore: true, totalCount: 12 } },
}
export const SavedView: Story = {
    decorators: [withConversationsProjectState(true)],
    args: {
        config: { ...DEFAULT_CONFIG, savedViewId: 'needs-reply' },
        result: { results: tickets, hasMore: true, totalCount: 12 },
    },
}
export const Loading: Story = {
    decorators: [withConversationsProjectState(true)],
    args: { loading: true },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export const Empty: Story = {
    decorators: [withConversationsProjectState(true)],
    args: { result: { results: [] } },
}
export const SetupUnavailable: Story = {
    decorators: [withConversationsProjectState(false)],
    parameters: {
        docs: {
            description: {
                story: 'Uses the Support availability guard when Support is disabled for the project.',
            },
        },
    },
}
