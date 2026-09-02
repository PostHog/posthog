import type { Meta, StoryObj } from '@storybook/react'

import type { CustomPropertySyncRunApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { CustomPropertySyncRuns } from './CustomPropertySyncRuns'

const accountRuns: CustomPropertySyncRunApi[] = [
    {
        id: '01890000-0000-0000-0000-0000000000c1',
        job_id: '019f0000-0000-7000-8000-000000000001',
        account_segment: 'tracked',
        sync_phase: 'completed',
        attempt: 1,
        workflow_id: 'sync-warehouse-account-properties-job-1-tracked',
        workflow_run_id: '01890000-0000-4000-8000-0000000000d1',
        temporal_url:
            'https://temporal.example.com/namespaces/default/workflows/sync-warehouse-account-properties-job-1-tracked/01890000-0000-4000-8000-0000000000d1',
        trigger: 'scheduled',
        status: 'completed',
        started_at: '2026-08-21T14:29:00Z',
        finished_at: '2026-08-21T14:30:00Z',
        rows_read: 4210,
        changed: 118,
        existing: 112,
        produced: 112,
        skipped_missing_person: 6,
        error: null,
        created_at: '2026-08-21T14:29:00Z',
    },
    {
        id: '01890000-0000-0000-0000-0000000000c2',
        job_id: '019f0000-0000-7000-8000-000000000001',
        account_segment: 'ignored',
        sync_phase: 'staging',
        attempt: 3,
        workflow_id: 'stage-warehouse-account-properties-job-1',
        workflow_run_id: '01890000-0000-4000-8000-0000000000d2',
        temporal_url: null,
        trigger: 'scheduled',
        status: 'failed',
        started_at: '2026-08-21T14:29:00Z',
        finished_at: '2026-08-21T14:35:00Z',
        rows_read: 0,
        changed: 0,
        existing: 0,
        produced: 0,
        skipped_missing_person: 0,
        error: "Couldn't prepare warehouse rows. Run the source view again. If it keeps failing, contact support.",
        created_at: '2026-08-21T14:29:00Z',
    },
]

const meta: Meta<typeof CustomPropertySyncRuns> = {
    title: 'Customer analytics/Custom property sync runs',
    component: CustomPropertySyncRuns,
    args: {
        runs: accountRuns,
        loading: false,
        loadFailed: false,
        targetType: 'account',
        syncsUrl: null,
        searchTerm: '',
        entryCount: accountRuns.length,
        currentPage: 1,
        onSearch: () => undefined,
        onForward: () => undefined,
        onBackward: () => undefined,
        onReload: () => undefined,
    },
    parameters: {
        layout: 'padded',
        mockDate: '2026-08-21T15:00:00Z',
    },
}

export default meta

type Story = StoryObj<typeof CustomPropertySyncRuns>

export const AccountLifecycle: Story = {}

export const Loading: Story = {
    args: { runs: [], loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
