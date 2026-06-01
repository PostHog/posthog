import type { Meta, StoryObj } from '@storybook/react'
import type { ReactNode } from 'react'

import { DashboardPlacement } from '~/types'

import { WidgetCard } from '../../components/WidgetCard/WidgetCard'
import { WidgetCardBody } from '../../components/WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../../components/WidgetCard/WidgetCardHeader'
import {
    mockMoreOverlay,
    widgetTileFrameDecorator,
    withSessionReplayProjectState,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { sessionReplaySampleRecordings } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { WidgetRuntimeAvailabilityGuard } from '../../components/WidgetRuntimeAvailabilityGuard/WidgetRuntimeAvailabilityGuard'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetComponentProps } from '../registry'
import { SessionReplayWidget } from './SessionReplayWidget'

const SESSION_REPLAY_CATALOG = getDashboardWidgetCatalogEntry('session_replay_list')!
const DEFAULT_CONFIG = SESSION_REPLAY_CATALOG.defaultConfig as Record<string, unknown>

type SessionReplayWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
}

function SessionReplayWidgetTileStory({
    title = '',
    description = 'Recent session recordings you can open in the replay player.',
    showDescription = true,
    body,
    ...widgetProps
}: SessionReplayWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = SESSION_REPLAY_CATALOG.groupLabel ?? 'Session replay'
    const defaultTitle = SESSION_REPLAY_CATALOG.headerTitle ?? SESSION_REPLAY_CATALOG.label

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={SESSION_REPLAY_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={SESSION_REPLAY_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={SESSION_REPLAY_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            <WidgetCardBody>{body ?? <SessionReplayWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof SessionReplayWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Session replay/Recent recordings',
    component: SessionReplayWidgetTileStory,
    parameters: {
        layout: 'padded',
    },
    decorators: [...widgetTileFrameDecorator],
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

type Story = StoryObj<typeof SessionReplayWidgetTileStory>

export const Populated: Story = {
    decorators: [withSessionReplayProjectState(true)],
    args: {
        title: 'Recent recordings',
        config: { ...DEFAULT_CONFIG, orderBy: 'start_time' },
        loading: false,
        result: {
            results: sessionReplaySampleRecordings,
            hasMore: true,
            limit: 10,
        },
    },
}

export const Loading: Story = {
    decorators: [withSessionReplayProjectState(true)],
    args: {
        title: 'Recent recordings',
        config: DEFAULT_CONFIG,
        loading: true,
        result: null,
    },
}

export const Empty: Story = {
    decorators: [withSessionReplayProjectState(true)],
    args: {
        title: 'Recent recordings',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { results: [] },
    },
}

export const SetupUnavailable: Story = {
    decorators: [withSessionReplayProjectState(false)],
    render: (args: SessionReplayWidgetTileStoryProps) => (
        <SessionReplayWidgetTileStory
            {...args}
            body={
                <WidgetRuntimeAvailabilityGuard availability={SESSION_REPLAY_CATALOG.availability}>
                    <SessionReplayWidget {...args} />
                </WidgetRuntimeAvailabilityGuard>
            }
        />
    ),
    args: {
        title: 'Recent recordings',
        config: DEFAULT_CONFIG,
        loading: false,
        result: null,
    },
    parameters: {
        docs: {
            description: {
                story: 'Uses catalog `session_replay_enabled` availability via `WidgetRuntimeAvailabilityGuard` when session replay is disabled.',
            },
        },
    },
}
