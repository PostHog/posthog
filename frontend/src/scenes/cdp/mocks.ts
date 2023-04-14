import { mockBasicUser } from '~/test/mocks'
import { ConnectionChoiceType, ConnectionType, ExportRunType } from './types'

export const mockConnections: ConnectionType[] = [
    {
        id: '1',
        name: 'Webhook export',
        status: 'Streaming',
        type: 'Event streaming',
        successRate: '100%',
        imageUrl: 'https://a.slack-edge.com/80588/img/services/outgoing-webhook_512.png',
    },
    {
        id: '2',
        name: 'S3 export',
        status: 'Scheduled every hour',
        type: 'Batch export',
        successRate: '100%',
        imageUrl: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
    },
]

export const mockConnectionChoices: ConnectionChoiceType[] = [
    {
        id: 'webhook-export',
        name: 'Webhook export',
        imageUrl: 'https://a.slack-edge.com/80588/img/services/outgoing-webhook_512.png',
        type: 'Event streaming',
    },
    {
        id: 's3-export',
        name: 'S3 export',
        imageUrl: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'Batch export',
    },
]

// one mock of each type of status: 'Running' | 'Cancelled' | 'Completed' | 'ContinuedAsNew' | 'Failed' | 'Terminated' | 'TimedOut'
export const mockExportRuns: ExportRunType[] = [
    {
        id: '1',
        status: 'Completed',
        created_at: '2021-05-10T12:00:00Z',
        completed_at: '2021-05-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        row_count: 100,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
    {
        id: '2',
        status: 'Starting',
        created_at: '2021-06-10T12:00:00Z',
        completed_at: '2021-06-10T13:00:00Z',
        created_by: null,
        export_schedule_id: '1',
    },
    {
        id: '3',
        status: 'Running',
        created_at: '2021-07-10T12:00:00Z',
        completed_at: '2021-07-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
    },
    {
        id: '4',
        status: 'Failed',
        created_at: '2021-08-10T12:00:00Z',
        completed_at: '2021-08-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
    },
    {
        id: '5',
        status: 'Paused',
        created_at: '2021-09-10T12:00:00Z',
        completed_at: '2021-09-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
    },
    {
        id: '6',
        status: 'Terminated',
        created_at: '2021-10-10T12:00:00Z',
        completed_at: '2021-10-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
    },
    {
        id: '6',
        status: 'TimedOut',
        created_at: '2021-10-10T12:00:00Z',
        completed_at: '2021-10-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
    },
]
