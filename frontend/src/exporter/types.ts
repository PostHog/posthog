import { DashboardType, InsightModel, TeamType } from '~/types'

export enum ExportType {
    Image = 'image',
    Embed = 'embed',
    Scene = 'scene',
}

export interface ExportOptions {
    whitelabel?: boolean
    noHeader?: boolean
    legend?: boolean
    fitScreen?: boolean
}

export interface ExportedData extends ExportOptions {
    type: ExportType
    dashboard?: Partial<DashboardType>
    insight?: InsightModel
    team?: Partial<TeamType>
}
