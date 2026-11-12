import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { EventsRetentionDeletionWarning } from './EventsRetentionDeletionWarning'

function SidebarWarning({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    return (
        <div className={isCollapsed ? 'w-fit' : 'w-[var(--project-navbar-width)]'}>
            <EventsRetentionDeletionWarning isCollapsed={isCollapsed} />
        </div>
    )
}

const meta: Meta<typeof SidebarWarning> = {
    title: 'Layout/Navigation sidebar/Events retention deletion warning',
    component: SidebarWarning,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/events_retention/': {
                    project_retention_months: null,
                    organization_retention_months: null,
                    default_retention_months: 24,
                    default_period_deletes: true,
                    next_deletion_on: '2026-12-03',
                },
                '/api/projects/:team_id/events_retention/scheduled_deletion_count/': {
                    deletes_on: '2026-12-03',
                    deletes_before: '2024-12-01',
                    events_deleted: 1_200_000,
                },
            },
        }),
    ],
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof SidebarWarning>

export const Expanded: Story = {
    args: { isCollapsed: false },
    parameters: { testOptions: { waitForSelector: '[data-attr="nav-events-retention-deletion-warning-settings"]' } },
}

export const Collapsed: Story = {
    args: { isCollapsed: true },
    parameters: { testOptions: { waitForSelector: '[data-attr="nav-events-retention-deletion-warning"]' } },
}
