import { Dayjs } from 'lib/dayjs'
import { UserBasicType } from '~/types'

// A better name for the following would be
export type ConnectionDestinationType = 'Event streaming' | 'Batch export'

export type ConnectionChoiceType = {
    id: string
    name: string
    imageUrl: string
    type: ConnectionDestinationType
}

export type BatchExportConnectionType = {
    id?: string
    name: string
    status: string
    connection_type_id: string
    successRate: string
    imageUrl: string
    settings: Record<string, unknown>
}

export type BatchExportSettingsType = {
    name: string
    frequency: BatchExportFrequencyType
    firstExport: Dayjs
    stopAtSpecificDate: false
    stopAt: Dayjs | undefined
    backfillRecords: boolean
    backfillFrom: Dayjs | undefined
    AWSAccessKeyID: string
    AWSSecretAccessKey: string
    AWSRegion: string
    AWSBucket: string
    fileFormat: FileFormatType
    fileName: string
}

export type CDPTabsType = 'connections' | 'history'

export type BatchExportTabsType = 'sync-history' | 'settings' | 'activity-log'

export type BatchExportFrequencyType = 'none' | '1' | '6' | '12' | 'daily' | 'weekly' | 'monthly'

export type FileFormatType = 'csv'

export enum BatchExportStatus {
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

export type ExportRunType = {
    id: string
    status: BatchExportStatus
    created_at: string
    completed_at: string
    export_schedule_id: string | null
    created_by: UserBasicType | null // null if created by a schedule, otherwise by a user
    filters?: string
    row_count?: number
    progress?: number
}

export enum ChangeExportRunStatusEnum {
    Pause = 'Pause',
    Resume = 'Resume',
    Restart = 'Restart',
    Delete = 'Delete',
}
