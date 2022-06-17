import { DashboardType, InsightModel, TeamType } from '~/types'

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
