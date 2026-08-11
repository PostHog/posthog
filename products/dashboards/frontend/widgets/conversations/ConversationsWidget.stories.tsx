import type { Meta, StoryObj } from '@storybook/react'

import { DashboardPlacement } from '~/types'

import { WidgetCard } from '../../components/WidgetCard/WidgetCard'
import { WidgetCardBody } from '../../components/WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../../components/WidgetCard/WidgetCardHeader'
import {
    mockMoreOverlay,
    widgetStorybookParameters,
    widgetTileFrameDecorator,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import type { DashboardWidgetComponentProps } from '../registry'
import { ConversationsWidget } from './ConversationsWidget'
import { ConversationsWidgetTileFilters } from './ConversationsWidgetTileFilters'

const CATALOG = getDashboardWidgetCatalogEntry('conversations_recent_tickets')!
const DEFAULT_CONFIG = CATALOG.defaultConfig as Record<string, unknown>

function StoryTile(props: DashboardWidgetComponentProps): JSX.Element {
    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={CATALOG.headerLayout}
                title=""
                defaultTitle={CATALOG.headerTitle ?? CATALOG.label}
                titleHref={CATALOG.titleHref}
                widgetTypeLabel={getDashboardWidgetGroupLabel(CATALOG.groupId)}
                config={props.config}
                headerMeta={CATALOG.headerMeta}
                description={CATALOG.description}
                showDescription
                loading={props.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            <ConversationsWidgetTileFilters
                tileId={props.tileId}
                config={props.config}
                onUpdateConfig={props.onUpdateConfig}
            />
            <WidgetCardBody>
                <ConversationsWidget {...props} />
            </WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof StoryTile> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Support/Recent tickets',
    component: StoryTile,
    parameters: { layout: 'padded', ...widgetStorybookParameters },
    decorators: widgetTileFrameDecorator,
    args: { tileId: 1, config: DEFAULT_CONFIG, loading: false, result: null, onUpdateConfig: () => undefined },
}
export default meta
type Story = StoryObj<typeof StoryTile>
const ticket = {
    id: 'ticket-1',
    ticket_number: 124,
    channel_source: 'email',
    status: 'open',
    priority: 'high',
    assignee: null,
    updated_at: '2026-05-26T09:55:00Z',
    last_message_text: 'Unable to finish checkout',
    unread_team_count: 1,
    email_subject: null,
}
export const Populated: Story = { args: { result: { results: [ticket], hasMore: true, totalCount: 12 } } }
export const Loading: Story = {
    args: { loading: true },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export const Empty: Story = { args: { result: { results: [] } } }
export const Error: Story = { args: { error: 'Request failed' } }
