import { Dayjs } from 'lib/dayjs'

// A better name for the following would be
export type ConnectionDestinationType = 'Event streaming' | 'Batch export'

export type ConnectionChoiceType = {
    id: string
    name: string
    imageUrl: string
    type: ConnectionDestinationType
}

export type BatchExportConnectionType = {
    id: string
    name: string
    status: string
    type: ConnectionDestinationType
    successRate: string
    imageUrl: string
    settings: BatchExportSettingsType
}

export type BatchExportSettingsType = {
    id?: string
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
