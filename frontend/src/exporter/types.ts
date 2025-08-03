import { DashboardType, DataColorThemeModel, InsightModel, SessionRecordingType } from '~/types'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

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
    autoplay?: boolean
    noBorder?: boolean
    mode?: SessionRecordingPlayerMode
}
