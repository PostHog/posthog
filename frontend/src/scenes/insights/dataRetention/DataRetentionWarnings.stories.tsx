import type { Meta, StoryObj } from '@storybook/react'

import { LemonBanner } from '@posthog/lemon-ui'

import { InsightMetaContent } from 'lib/components/Cards/InsightCard/InsightMeta'

const RETENTION_WARNING =
    "This insight's date range goes beyond your 1-year data retention, so events older than that aren't included."

const meta: Meta = {
    title: 'Scenes-App/Insights/Data retention warnings',
    parameters: {
        layout: 'padded',
        testOptions: { snapshotTargetSelector: '[data-attr="data-retention-warnings"]' },
    },
}
export default meta

// The dashboard banner and the per-tile icon, as rendered once the query response reports that the retention floor
// narrowed the scan. Presentational pieces only: the logic that decides when to show them is unit tested separately.
export const DashboardBannerAndTileIcon: StoryObj = {
    render: () => (
        <div data-attr="data-retention-warnings" className="flex flex-col gap-4 max-w-3xl">
            <LemonBanner type="warning" action={{ children: 'Upgrade plan', to: '#' }}>
                This insight's date range goes beyond your 1-year data retention, so events older than that aren't
                included.
            </LemonBanner>
            <LemonBanner type="warning" action={{ children: 'Upgrade plan', to: '#' }}>
                Some insights on this dashboard have date ranges that go beyond your 1-year data retention, so events
                older than that aren't included.
            </LemonBanner>
            <div className="grid grid-cols-2 gap-4">
                <div className="border rounded p-3 bg-surface-primary">
                    <InsightMetaContent
                        title="Weekly active users"
                        description="Unique users per week, all time"
                        dataRetentionWarning={RETENTION_WARNING}
                    />
                </div>
                <div className="border rounded p-3 bg-surface-primary">
                    <InsightMetaContent
                        title="Signups this month"
                        description="Inside the retention window, so no warning"
                    />
                </div>
            </div>
        </div>
    ),
}
