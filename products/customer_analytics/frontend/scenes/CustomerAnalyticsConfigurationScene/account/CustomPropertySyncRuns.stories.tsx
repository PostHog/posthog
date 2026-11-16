import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'

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

const PERSON_RUN_LOGS_SOURCE_ID = '01890000-0000-0000-0000-0000000000a1'
const PERSON_RUN_ID = '01890000-0000-4000-8000-0000000000e1'

const personRuns: CustomPropertySyncRunApi[] = [
    {
        id: '01890000-0000-0000-0000-0000000000b1',
        job_id: null,
        account_segment: null,
        sync_phase: null,
        attempt: null,
        workflow_id: null,
        workflow_run_id: PERSON_RUN_ID,
        temporal_url: null,
        trigger: 'manual',
        status: 'running',
        started_at: '2026-08-21T14:40:00Z',
        finished_at: null,
        rows_read: 96000,
        changed: 41000,
        existing: 38500,
        produced: 38500,
        skipped_missing_person: 2500,
        error: null,
        created_at: '2026-08-21T14:40:00Z',
    },
    {
        id: '01890000-0000-0000-0000-0000000000b2',
        job_id: 'job-2',
        account_segment: null,
        sync_phase: null,
        attempt: null,
        workflow_id: null,
        workflow_run_id: '01890000-0000-4000-8000-0000000000e2',
        temporal_url: null,
        trigger: 'scheduled',
        status: 'failed',
        started_at: '2026-08-21T12:00:00Z',
        finished_at: '2026-08-21T12:03:00Z',
        rows_read: 2000,
        changed: 300,
        existing: 0,
        produced: 0,
        skipped_missing_person: 0,
        error: 'Kafka did not confirm 300 of 300 property updates. A retry sends the undelivered updates again.',
        created_at: '2026-08-21T12:00:00Z',
    },
    {
        id: '01890000-0000-0000-0000-0000000000b3',
        job_id: 'job-1',
        account_segment: null,
        sync_phase: null,
        attempt: null,
        workflow_id: null,
        workflow_run_id: null,
        temporal_url: null,
        trigger: 'scheduled',
        status: 'completed',
        started_at: '2026-08-20T12:00:00Z',
        finished_at: '2026-08-20T12:01:00Z',
        rows_read: 1500,
        changed: 20,
        existing: 20,
        produced: 20,
        skipped_missing_person: 0,
        error: null,
        created_at: '2026-08-20T12:00:00Z',
    },
]

const personRunLogRows = [
    [PERSON_RUN_ID, '2026-08-21 14:40:01', 'info', 'Finding the latest row for each person'],
    [PERSON_RUN_ID, '2026-08-21 14:40:41', 'info', 'Read 48,000 rows'],
    [PERSON_RUN_ID, '2026-08-21 14:40:41', 'info', 'Checked 20,000 changed rows. 18,500 match a person.'],
    [PERSON_RUN_ID, '2026-08-21 14:40:41', 'info', 'Sent 18,500 updates'],
    [PERSON_RUN_ID, '2026-08-21 14:41:11', 'info', 'Read 96,000 rows'],
    [PERSON_RUN_ID, '2026-08-21 14:41:11', 'info', 'Checked 41,000 changed rows. 38,500 match a person.'],
    [PERSON_RUN_ID, '2026-08-21 14:41:11', 'info', 'Sent 38,500 updates'],
]

export const PersonRunProgress: Story = {
    args: {
        runs: personRuns,
        targetType: 'person',
        logSourceId: PERSON_RUN_LOGS_SOURCE_ID,
        entryCount: personRuns.length,
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': { results: [...personRunLogRows].reverse() },
            },
        }),
    ],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    play: async ({ canvasElement }) => {
        const [firstRun] = await within(canvasElement).findAllByTitle('Show more')
        await userEvent.click(firstRun)
        await within(canvasElement).findByText('Finding the latest row for each person')
    },
}
