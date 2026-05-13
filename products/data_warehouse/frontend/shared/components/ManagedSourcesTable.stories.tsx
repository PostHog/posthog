import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { ManagedSourcesTable } from './ManagedSourcesTable'

const meta: Meta<typeof ManagedSourcesTable> = {
    title: 'Scenes-App/Data Warehouse/Sources/ManagedSourcesTable',
    component: ManagedSourcesTable,
    parameters: {
        viewMode: 'story',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}

export default meta

type Story = StoryObj<typeof ManagedSourcesTable>

const baseSource = {
    created_at: '2026-05-13T08:00:00.000000Z',
    created_by: null,
    revenue_analytics_config: { enabled: false, include_invoiceless_charges: false },
    access_method: null,
    user_access_level: 'editor' as const,
    schemas: [] as unknown[],
}

const sources = [
    {
        ...baseSource,
        id: 'src-1',
        source_type: 'GoogleSheets',
        prefix: 'GSC_data',
        last_run_at: '2026-05-13T08:56:00Z',
        status: 'Completed',
        latest_error: null,
    },
    {
        ...baseSource,
        id: 'src-2',
        source_type: 'GoogleSheets',
        prefix: 'ahrefs_keyword_rankings',
        last_run_at: '2026-05-13T06:51:00Z',
        status: 'Completed',
        latest_error: null,
    },
    {
        ...baseSource,
        id: 'src-3',
        source_type: 'Postgres',
        prefix: 'revenue',
        last_run_at: '2026-05-13T10:44:00Z',
        status: 'Failed',
        latest_error: 'Connection timed out after 30s while reading from primary replica',
    },
    {
        ...baseSource,
        id: 'src-4',
        source_type: 'TikTokAds',
        prefix: '',
        last_run_at: '2026-05-13T10:40:00Z',
        status: 'Completed',
        latest_error: null,
    },
    {
        ...baseSource,
        id: 'src-5',
        source_type: 'LinkedinAds',
        prefix: '',
        last_run_at: '2025-12-18T13:44:00Z',
        status: 'Running',
        latest_error: null,
    },
]

/**
 * Reproduces the Sources table at /data-management/sources so we can verify locally whether status
 * tags render with cursor-pointer / role="button". The bug behind PR #58381 was that LemonTag's
 * onClick-based inference fired when Base UI's Tooltip injected its own onClick onto the Failed
 * tag. After the fix:
 *  - Completed (success) and Running (primary) tags should render without cursor-pointer or role="button".
 *  - The Failed (danger) tag is wrapped in a Tooltip and should also render without cursor-pointer / role="button", but its tooltip should still appear on hover.
 */
export const Default: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/': () => [
                    200,
                    { results: sources, count: sources.length, next: null, previous: null },
                ],
                '/api/environments/:team_id/external_data_sources/wizard/': () => [200, {}],
            },
        })
        return <ManagedSourcesTable />
    },
}
