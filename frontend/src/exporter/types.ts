import { DashboardType, InsightModel, OrganizationType, TeamType } from '~/types'

export enum ExportType {
    Image = 'image',
    Embed = 'embed',
    Scene = 'scene',
}

export interface ExportedData {
    type: ExportType
    dashboard?: Partial<DashboardType>
    insight?: InsightModel
    team?: Partial<TeamType>
    organization?: Partial<OrganizationType>
}
