import { mockBasicUser } from '~/test/mocks'
import {
    BatchExportDestinationType,
    S3BatchExportConfigType,
    BatchExportRunStatus,
    ConnectionChoiceType,
    BatchExportRunType,
} from './types'
import { dayjs } from 'lib/dayjs'

export const mockConnections: BatchExportDestinationType[] = [
    {
        id: '1',
        name: 'Webhook export',
        status: 'Streaming',
        connection_type_id: 'webhook-export',
        successRate: '100%',
        imageUrl: 'https://a.slack-edge.com/80588/img/services/outgoing-webhook_512.png',
        config: {},
    },
    {
        id: '2',
        name: 'S3 export',
        status: 'Scheduled every hour',
        connection_type_id: 's3-export',
        config: {},
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

export const mockExportRuns: BatchExportRunType[] = [
    {
        id: '1',
        status: BatchExportRunStatus.Completed,
        created_at: '2021-05-10T12:00:00Z',
        completed_at: '2021-05-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
        duration: 1000,
        metrics: {
            dates: [
                '2020-10-14T00:00:00.000Z',
                '2020-10-14T01:00:00.000Z',
                '2020-10-14T02:00:00.000Z',
                '2020-10-14T03:00:00.000Z',
                '2020-10-14T04:00:00.000Z',
            ],
            successes: [101, 100, 0, 0, 0],
            successes_on_retry: [0, 0, 100, 0, 0],
            failures: [0, 0, 0, 0, 103],
            totals: {
                successes: 101,
                successes_on_retry: 100,
                failures: 103,
            },
        },
        errors: [
            {
                error_type: 'invalid_credentials',
                count: 103,
                last_seen: '2020-10-14T00:00:00.000Z',
            },
        ],
    },
    {
        id: '2',
        status: BatchExportRunStatus.Starting,
        created_at: '2021-06-10T12:00:00Z',
        completed_at: '2021-06-10T13:00:00Z',
        created_by: null,
        export_schedule_id: '1',
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
    {
        id: '3',
        status: BatchExportRunStatus.Running,
        created_at: '2021-07-10T12:00:00Z',
        completed_at: '2021-07-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
        progress: 0.5,
    },
    {
        id: '4',
        status: BatchExportRunStatus.Failed,
        created_at: '2021-08-10T12:00:00Z',
        completed_at: '2021-08-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
        duration: 1000,
        failure_reason: 'Something went wrong',
    },
    {
        id: '5',
        status: BatchExportRunStatus.Paused,
        created_at: '2021-09-10T12:00:00Z',
        completed_at: '2021-09-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
    {
        id: '6',
        status: BatchExportRunStatus.Terminated,
        created_at: '2021-10-10T12:00:00Z',
        completed_at: '2021-10-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
        failed_rows: 10,
    },
    {
        id: '6',
        status: BatchExportRunStatus.TimedOut,
        created_at: '2021-10-10T12:00:00Z',
        completed_at: '2021-10-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
]

export const mockConnectionSettings: S3BatchExportConfigType = {
    name: '',
    frequency: '6',
    firstExport: dayjs(),
    stopAtSpecificDate: false,
    stopAt: undefined,
    backfillRecords: false,
    backfillFrom: undefined,
    AWSAccessKeyID: '',
    AWSSecretAccessKey: 'test',
    AWSRegion: '',
    AWSBucket: '',
    fileFormat: 'csv',
    fileName: '',
}
