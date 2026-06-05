import type { Meta, StoryObj } from '@storybook/react'
import type { ReactNode } from 'react'

import { DashboardPlacement } from '~/types'

import { WidgetCard } from '../../components/WidgetCard/WidgetCard'
import { WidgetCardBody } from '../../components/WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../../components/WidgetCard/WidgetCardHeader'
import {
    mockMoreOverlay,
    widgetTileFrameDecorator,
    withErrorTrackingProjectState,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import type { DashboardWidgetComponentProps } from '../registry'
import { ErrorTrackingWidget } from './ErrorTrackingWidget'

const ERROR_TRACKING_CATALOG = getDashboardWidgetCatalogEntry('error_tracking_list')!
const DEFAULT_CONFIG = ERROR_TRACKING_CATALOG.defaultConfig as Record<string, unknown>

type ErrorTrackingWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
}

function ErrorTrackingWidgetTileStory({
    title = '',
    description = 'Track the most common errors affecting your users.',
    showDescription = true,
    body,
    ...widgetProps
}: ErrorTrackingWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(ERROR_TRACKING_CATALOG.groupId)
    const defaultTitle = ERROR_TRACKING_CATALOG.headerTitle ?? ERROR_TRACKING_CATALOG.label

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={ERROR_TRACKING_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={ERROR_TRACKING_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={ERROR_TRACKING_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            <WidgetCardBody>{body ?? <ErrorTrackingWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

const sampleIssues = [
    {
        id: 'issue-1',
        name: 'TypeError: Cannot read properties of undefined',
        description: 'User profile settings fail to load when the session cache is empty.',
        function: 'loadProfile',
        source: 'https://app.example.test/static/js/settings.js',
        library: 'web',
        status: 'active',
        assignee: null,
        first_seen: '2026-05-01T10:00:00.000Z',
        last_seen: '2026-05-26T08:00:00.000Z',
        aggregations: {
            occurrences: 42,
            sessions: 18,
            users: 12,
            volume_buckets: [
                { label: '2026-05-20T00:00:00.000Z', value: 2 },
                { label: '2026-05-21T00:00:00.000Z', value: 4 },
                { label: '2026-05-22T00:00:00.000Z', value: 8 },
                { label: '2026-05-23T00:00:00.000Z', value: 12 },
                { label: '2026-05-24T00:00:00.000Z', value: 6 },
                { label: '2026-05-25T00:00:00.000Z', value: 5 },
                { label: '2026-05-26T00:00:00.000Z', value: 5 },
            ],
        },
    },
    {
        id: 'issue-2',
        name: 'NetworkError: Failed to fetch',
        description: 'Checkout requests fail when the payment API is unavailable.',
        function: 'fetch',
        source: 'https://app.example.test/static/js/api.js',
        library: 'web',
        status: 'pending_release',
        assignee: null,
        first_seen: '2026-05-10T10:00:00.000Z',
        last_seen: '2026-05-25T12:00:00.000Z',
        aggregations: {
            occurrences: 18,
            sessions: 9,
            users: 7,
            volume_buckets: [
                { label: '2026-05-20T00:00:00.000Z', value: 1 },
                { label: '2026-05-21T00:00:00.000Z', value: 2 },
                { label: '2026-05-22T00:00:00.000Z', value: 3 },
                { label: '2026-05-23T00:00:00.000Z', value: 2 },
                { label: '2026-05-24T00:00:00.000Z', value: 4 },
                { label: '2026-05-25T00:00:00.000Z', value: 3 },
                { label: '2026-05-26T00:00:00.000Z', value: 3 },
            ],
        },
    },
]

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof ErrorTrackingWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Error tracking/Top issues',
    component: ErrorTrackingWidgetTileStory,
    parameters: {
        layout: 'padded',
        mockDate: '2026-05-26T10:00:00',
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

type Story = StoryObj<typeof ErrorTrackingWidgetTileStory>

export const Populated: Story = {
    decorators: [withErrorTrackingProjectState(true)],
    args: {
        title: 'Top issues',
        config: { ...DEFAULT_CONFIG, orderBy: 'occurrences' },
        loading: false,
        result: {
            results: sampleIssues,
            hasMore: true,
            limit: 10,
        },
    },
}

export const Loading: Story = {
    decorators: [withErrorTrackingProjectState(true)],
    args: {
        title: 'Top issues',
        config: DEFAULT_CONFIG,
        loading: true,
        result: null,
    },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const Empty: Story = {
    decorators: [withErrorTrackingProjectState(true)],
    args: {
        title: 'Top issues',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { results: [] },
    },
    parameters: {
        docs: {
            description: {
                story: 'Celebratory empty state when no issues match the widget filters.',
            },
        },
    },
}

export const SetupUnavailable: Story = {
    args: {
        title: 'Top issues',
        config: DEFAULT_CONFIG,
        loading: false,
        result: null,
    },
    decorators: [withErrorTrackingProjectState(false)],
    parameters: {
        docs: {
            description: {
                story: 'Uses the shared `ErrorTrackingIngestionPrompt` from error tracking (via `ErrorTrackingWidget`) when exception autocapture is disabled and no exceptions have been captured.',
            },
        },
    },
}
