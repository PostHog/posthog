import { mockBasicUser } from '~/test/mocks'
import {
    BatchExportConnectionType,
    BatchExportSettingsType,
    BatchExportStatus,
    ConnectionChoiceType,
    ExportRunType,
} from './types'
import { dayjs } from 'lib/dayjs'

export const mockConnections: BatchExportConnectionType[] = [
    {
        id: '1',
        name: 'Webhook export',
        status: 'Streaming',
        connection_type_id: 'webhook-export',
        successRate: '100%',
        imageUrl: 'https://a.slack-edge.com/80588/img/services/outgoing-webhook_512.png',
        settings: {},
    },
    {
        id: '2',
        name: 'S3 export',
        status: 'Scheduled every hour',
        connection_type_id: 's3-export',
        settings: {},
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

export const mockExportRuns: ExportRunType[] = [
    {
        id: '1',
        status: BatchExportStatus.Completed,
        created_at: '2021-05-10T12:00:00Z',
        completed_at: '2021-05-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        row_count: 100,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
    {
        id: '2',
        status: BatchExportStatus.Starting,
        created_at: '2021-06-10T12:00:00Z',
        completed_at: '2021-06-10T13:00:00Z',
        created_by: null,
        export_schedule_id: '1',
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
    {
        id: '3',
        status: BatchExportStatus.Running,
        created_at: '2021-07-10T12:00:00Z',
        completed_at: '2021-07-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
        progress: 0.5,
    },
    {
        id: '4',
        status: BatchExportStatus.Failed,
        created_at: '2021-08-10T12:00:00Z',
        completed_at: '2021-08-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
    {
        id: '5',
        status: BatchExportStatus.Paused,
        created_at: '2021-09-10T12:00:00Z',
        completed_at: '2021-09-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
    {
        id: '6',
        status: BatchExportStatus.Terminated,
        created_at: '2021-10-10T12:00:00Z',
        completed_at: '2021-10-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
    {
        id: '6',
        status: BatchExportStatus.TimedOut,
        created_at: '2021-10-10T12:00:00Z',
        completed_at: '2021-10-10T13:00:00Z',
        created_by: mockBasicUser,
        export_schedule_id: null,
        filters: '2021-05-10T11:00:00Z to 2021-05-10T12:00:00Z',
    },
]

export const mockConnectionSettings: BatchExportSettingsType = {
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
