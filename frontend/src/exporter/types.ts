import { DashboardType, InsightModel, InsightShortId, TeamType } from '~/types'

export enum ExportType {
    Image = 'image',
    Embed = 'embed',
    Scene = 'scene',
}

export interface ExportedData {
    type: ExportType
    whitelabel?: boolean
    dashboard?: Partial<DashboardType>
    insight?: InsightModel
    team?: Partial<TeamType>
}

export interface ExportPreviewParams {
    insight?: InsightShortId
    dashboardId?: number
    whitelabel?: boolean
}
