import { DashboardType, DataColorThemeModel, InsightModel, SessionRecordingType } from '~/types'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'

export enum ExportType {
    Image = 'image',
    Embed = 'embed',
    Scene = 'scene',
}

export interface ExportedData extends SharingConfigurationSettings {
    accessToken?: string
    type: ExportType
    dashboard?: DashboardType
    insight?: InsightModel
    themes?: DataColorThemeModel[]
    recording?: SessionRecordingType
}
