import type { Meta, StoryObj } from '@storybook/react'
import type { ReactNode } from 'react'

import { DashboardPlacement } from '~/types'

import { WidgetCard } from './WidgetCard'
import { WidgetCardBody, WidgetCardBodyMessage, WidgetLoadingState } from './WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from './WidgetCardHeader'
import {
    dashboardTileTopHeading,
    mockMoreOverlay,
    sampleListBody,
    widgetTileFrameDecorator,
} from './widgetCardStoryFixtures'

type WidgetCardStoryProps = {
    placement: DashboardPlacement
    showEditingControls?: boolean
    className?: string
    headerLayout: 'dashboard_tile' | 'simple'
    title: string
    topHeading?: ReactNode
    description?: string
    showDescription?: boolean
    loading?: boolean
    moreButtonOverlay?: ReactNode
    locked?: boolean
    lockedMessage?: string
    body?: ReactNode
}

function WidgetCardStory({
    placement,
    showEditingControls,
    className,
    headerLayout,
    title,
    topHeading,
    description,
    showDescription,
    loading,
    moreButtonOverlay,
    locked,
    lockedMessage,
    body,
}: WidgetCardStoryProps): JSX.Element {
    return (
        <WidgetCard className={className}>
            <WidgetCardHeader
                layout={headerLayout}
                title={title}
                topHeading={topHeading}
                description={description}
                showDescription={showDescription}
                loading={loading}
                showEditingControls={showEditingControls}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(placement, showEditingControls)}
                moreButtonOverlay={moreButtonOverlay}
            />
            <WidgetCardBody locked={locked} lockedMessage={lockedMessage}>
                {body}
            </WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof WidgetCardStory> = {
    title: 'Dashboards/Dashboard Widgets/WidgetCard',
    component: WidgetCardStory,
    parameters: {
        layout: 'padded',
    },
    decorators: widgetTileFrameDecorator,
    args: {
        placement: DashboardPlacement.Dashboard,
        showEditingControls: false,
        className: 'h-full',
        headerLayout: 'dashboard_tile',
        title: 'Sample metric',
        topHeading: dashboardTileTopHeading,
    },
}

export default meta

type Story = StoryObj<typeof WidgetCardStory>

export const DashboardTilePopulated: Story = {
    args: {
        headerLayout: 'dashboard_tile',
        title: 'Sample metric',
        topHeading: dashboardTileTopHeading,
        description: 'A short description of what this widget shows on the dashboard.',
        showDescription: true,
        showEditingControls: true,
        moreButtonOverlay: mockMoreOverlay,
        body: sampleListBody,
    },
}

export const SimpleHeaderLoading: Story = {
    args: {
        headerLayout: 'simple',
        title: 'Custom metric',
        loading: true,
        body: <WidgetLoadingState />,
    },
}

export const Locked: Story = {
    args: {
        title: 'Restricted widget',
        locked: true,
        lockedMessage: 'You need editor access to view this widget.',
    },
    parameters: {
        docs: {
            description: {
                story: 'Locked widgets show a centered lock icon with the access message in the body.',
            },
        },
    },
}

export const EmptyBodyMessage: Story = {
    args: {
        body: (
            <WidgetCardBodyMessage>
                No data matches your filters. Adjust the date range or filters in widget settings.
            </WidgetCardBodyMessage>
        ),
    },
}

export const SetupUnavailablePattern: Story = {
    args: {
        body: (
            <WidgetCardBodyMessage>
                <div className="flex max-w-sm flex-col items-center gap-2">
                    <div className="font-semibold text-primary">Enable this feature to use the widget</div>
                    <p className="m-0 text-muted">
                        Turn on the required product capability in project settings. See{' '}
                        <code>WidgetAvailabilitySetupPrompt</code> for the full gated UI (requires team logic).
                    </p>
                </div>
            </WidgetCardBodyMessage>
        ),
    },
    parameters: {
        docs: {
            description: {
                story: 'Catalog-driven setup uses `WidgetAvailabilitySetupPrompt` (Kea-backed). This story shows the centered body pattern only.',
            },
        },
    },
}
