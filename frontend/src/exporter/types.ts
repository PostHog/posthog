import { DashboardType, DataColorThemeModel, InsightModel, SessionRecordingType } from '~/types'

export enum ExportType {
    Image = 'image',
    Embed = 'embed',
    Scene = 'scene',
}

export interface ExportOptions {
    whitelabel?: boolean
    noHeader?: boolean
    legend?: boolean
    detailed?: boolean
    // Recording options
    showInspector?: boolean
}

export interface ExportedData extends ExportOptions {
    accessToken?: string
    type: ExportType
    dashboard?: DashboardType
    insight?: InsightModel
    themes?: DataColorThemeModel[]
    recording?: SessionRecordingType
}
