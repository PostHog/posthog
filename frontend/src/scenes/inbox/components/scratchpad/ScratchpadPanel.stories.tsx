import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { ScratchpadPanel } from './ScratchpadPanel'

// Scouts write whatever markdown suits them, so the mock bodies deliberately mix headings,
// bold runs, nested bullets, and plain prose — the panel has to read evenly across all of it.
const mockEntries: ScratchpadEntryApi[] = [
    {
        key: 'report:slo_monitoring:analytic-platform:export:US',
        content:
            'Report 019f94de remains the live pending-input US export SLO report, refreshed 2026-08-05 with continued TableAccessDeniedError-led burn.',
        created_at: '2026-08-01T06:35:04Z',
        updated_at: '2026-08-05T12:05:59Z',
        created_by_run_id: 'run-1',
        created_by_skill: 'signals-scout-slo-monitoring',
        created_by_run_url: '/tasks/run-1',
    },
    {
        key: 'dedupe:slo_monitoring:analytic-platform:export:US',
        content:
            '## Live-covered breach – refreshed 2026-08-05 11:05 UTC\n\n- Report 019f94de remains canonical and was edited in place.\n- No new report minted for the continuing breach.',
        created_at: '2026-08-02T06:35:04Z',
        updated_at: '2026-08-05T12:05:58Z',
        created_by_run_id: 'run-2',
        created_by_skill: 'signals-scout-slo-monitoring',
        created_by_run_url: '/tasks/run-2',
    },
    {
        key: 'pattern:slo_monitoring:latest-summary',
        content:
            '# Latest SLO scan – 2026-08-05 11:05 UTC\n\n- Checked all 16 canonical US/EU operation-region pairs with the refreshed 28-day insights.\n- **Latest complete hour** coverage reached across every family.\n- No new breach beyond the live-covered US export burn.',
        created_at: '2026-08-03T06:35:04Z',
        updated_at: '2026-08-05T12:05:58Z',
        created_by_run_id: 'run-3',
        created_by_skill: 'signals-scout-slo-monitoring',
        created_by_run_url: '/tasks/run-3',
    },
    {
        key: 'baseline:self_driving_dashboards:insight:WdDay8ev',
        content:
            '### MCP p95 latency baseline\n\n- **Refreshed:** 2026-08-05 UTC.\n- Latest reliable complete hour remained populated across families: scouts about **375 ms**, inbox about **2.36 s**, workflows about **1.14 s**.\n- The detector returned no triggered dates for the current 14-day family latency series; no broad p95 regression established.',
        created_at: '2026-08-01T06:35:04Z',
        updated_at: '2026-08-05T12:05:36Z',
        created_by_run_id: 'run-4',
        created_by_skill: 'signals-scout-self-driving-dashboards',
        created_by_run_url: '/tasks/run-4',
    },
    {
        key: 'watch:error_tracking:new-release-regression',
        content:
            'Watching `TypeError: e.map is not a function` in the dashboard scene after the 1.43 release; volume still under the alert floor but climbing (~40/day).',
        created_at: '2026-08-04T06:35:04Z',
        updated_at: '2026-08-05T09:12:00Z',
        created_by_run_id: null,
        created_by_skill: 'signals-scout-error-tracking',
        created_by_run_url: null,
    },
    {
        key: 'tags:errors:taxonomy',
        content:
            'Settled vocabulary for error grouping:\n\n1. `ingestion` – capture + pipeline failures\n2. `query` – ClickHouse timeouts and OOMs\n3. `frontend` – scene-level TypeErrors',
        created_at: '2026-07-20T06:35:04Z',
        updated_at: '2026-08-05T08:00:00Z',
        created_by_run_id: 'run-6',
        created_by_skill: 'signals-scout-general',
        created_by_run_url: '/tasks/run-6',
    },
]

const meta: Meta = {
    title: 'Scenes-App/Inbox/Scratchpad',
    component: ScratchpadPanel,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-05',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/scratchpad/': () => [200, mockEntries],
            },
        }),
    ],
}
export default meta

type Story = StoryObj

export const Scratchpad: Story = {}

export const EmptyScratchpad: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/scratchpad/': () => [200, []],
            },
        }),
    ],
}
