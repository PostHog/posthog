import { Dayjs } from 'lib/dayjs'
import { AppErrorSummary, AppMetrics } from 'scenes/apps/appMetricsSceneLogic'
import { UserBasicType } from '~/types'

export enum ConnectionDestinationEnum {
    EventStreaming = 'Event streaming',
    BatchExport = 'Batch export',
}

export type ConnectionChoiceType = {
    id: string
    name: string
    imageUrl: string
    type: ConnectionDestinationEnum
}

export type CDPTabsType = 'connections' | 'history'

export type BatchExportTabsType = 'sync-history' | 'settings' | 'activity-log'

export type BatchExportDestinationType = {
    id: string
    name: string
    status: string
    connection_type_id: string // TODO: convert to string id
    successRate: string
    imageUrl: string
    config: Record<string, unknown>
    createdAt?: string
    lastUpdatedAt?: string
}

export type S3ConfigType = {
    AWSAccessKeyID: string
    AWSSecretAccessKey: string
    AWSRegion: string
    AWSBucket: string
    fileFormat: S3BatchExportFileFormatType
    fileName: string
}

export type S3BatchExportConfigType = {
    name: string
    frequency: BatchExportFrequencyType
    firstExport: Dayjs // TODO: convert dayjs to strings for saving
    stopAtSpecificDate: false
    stopAt: Dayjs | undefined
    backfillRecords: boolean
    backfillFrom: Dayjs | undefined
    AWSAccessKeyID: string
    AWSSecretAccessKey: string
    AWSRegion: string
    AWSBucket: string
    fileFormat: S3BatchExportFileFormatType
    fileName: string
}

export type BatchExportFrequencyType = 'none' | '1' | '6' | '12' | 'daily' | 'weekly' | 'monthly'

export type S3BatchExportFileFormatType = 'csv'

export enum BatchExportRunStatus {
    Running = 'Running',
    Cancelled = 'Cancelled',
    Completed = 'Completed',
    ContinuedAsNew = 'ContinuedAsNew',
    Failed = 'Failed',
    Terminated = 'Terminated',
    TimedOut = 'TimedOut',
    Starting = 'Starting',
    Paused = 'Paused',
}

export type BatchExportRunType = {
    id: string
    status: BatchExportRunStatus
    created_at: string
    completed_at: string
    export_schedule_id: string | null
    created_by: UserBasicType | null // null if created by a schedule, otherwise by a user
    filters?: string

    metrics?: AppMetrics
    errors?: Array<AppErrorSummary>

    progress?: number
    duration?: number // in seconds
    failure_reason?: string
}

export enum ChangeExportRunStatusEnum {
    Pause = 'Pause',
    Resume = 'Resume',
    Restart = 'Restart',
    Delete = 'Delete',
}

// TODO do we need this on the frontend? Seems like it's only for the backend
export interface BatchExportSchedule {
    id: string
    batch_export_destination_id: string
    intervals: {
        every: string // time in seconds
        offset: string // time in seconds
    }[]
    offset: string // time in seconds
    team_id: string
    created_at: string
    last_updated_at: string
    paused_at: string | null
    unpaused_at: string | null
    start_at: string | null
    end_at?: string
    skip: Record<string, unknown>[]
    jitter: number | null
    time_zone_name: string | null
    // cron_expressions: string[]
    // calendars: Record<string, unknown>[]
}

export type DestinationConfigs = S3ConfigType // Add more types here as we add more destinations

export type CreateBatchExportScheduleType = {
    name: string
    type: string // TODO: rename this e.g. destination_slug or id?
    config: DestinationConfigs
    schedule?: {
        start_at: BatchExportSchedule['start_at']
        end_at: BatchExportSchedule['end_at']
        intervals: BatchExportSchedule['intervals']
    }
}
