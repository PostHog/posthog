import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { DashboardType, DataColorThemeModel, HeatmapExportContext, InsightModel, SessionRecordingType } from '~/types'

export enum ExportType {
    Image = 'image',
    Embed = 'embed',
    Scene = 'scene',
    Unlock = 'unlock',
    Heatmap = 'heatmap',
}

export interface ExportedData extends SharingConfigurationSettings {
    accessToken?: string
    shareToken?: string // JWT token for password-protected shares
    type: ExportType
    dashboard?: DashboardType
    insight?: InsightModel
    themes?: DataColorThemeModel[]
    recording?: SessionRecordingType
    autoplay?: boolean
    /** Player adds border by default - we want to remove it **/
    noBorder?: boolean
    mode?: SessionRecordingPlayerMode
    exportToken?: string
    heatmap_url?: string
    heatmap_context?: HeatmapExportContext
}
