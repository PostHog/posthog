import { DashboardType, DataColorThemeModel, InsightModel, SessionRecordingType } from '~/types'

export enum ExportType {
    Image = 'image',
    Embed = 'embed',
    Scene = 'scene',
    Unlock = 'unlock',
}

export interface ExportOptions {
    whitelabel?: boolean
    noHeader?: boolean
    legend?: boolean
    detailed?: boolean
    hideExtraDetails?: boolean
    // Recording options
    showInspector?: boolean
    mode?: any // SessionRecordingPlayerMode
    autoplay?: boolean
    noBorder?: boolean
}

export interface ExportedData extends ExportOptions {
    accessToken?: string
    shareToken?: string // JWT token for password-protected shares
    exportToken?: string
    type: ExportType
    dashboard?: DashboardType
    insight?: InsightModel
    themes?: DataColorThemeModel[]
    recording?: SessionRecordingType
}
