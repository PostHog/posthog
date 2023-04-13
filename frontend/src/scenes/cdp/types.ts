export type ConnectionChoiceType = {
    id: string
    name: string
    imageUrl: string
    type: 'Event streaming' | 'Batch export'
}

export type ConnectionType = {
    id: string
    name: string
    status: string
    type: 'Event streaming' | 'Batch export'
    successRate: string
    imageUrl: string
}

export type BatchExportSettings = {
    id: string
    name: string
    frequency: BatchExportFrequencyType
    startAt: string
    endAt: string
    backfillOnFirstRun: boolean
    sourceTable: string
    AWSAccessKeyID: string
    AWSSecretAccessKey: string
    AWSRegion: string
    AWSBucket: string
    AWSKeyPrefix: string
    fileFormat: FileFormatType
}

export type CDPTabsType = 'connections' | 'history'

export type BatchExportTabsType = 'sync-history' | 'settings' | 'activity-log'

export type BatchExportFrequencyType = 'none' | '1' | '6' | '12' | 'daily' | 'weekly' | 'monthly'

export type FileFormatType = 'csv'
