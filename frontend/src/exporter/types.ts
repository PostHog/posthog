import { NotebookType } from 'scenes/notebooks/types'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { AnyResponseType, SharingConfigurationSettings } from '~/queries/schema/schema-general'
import {
    CohortType,
    DashboardType,
    DataColorThemeModel,
    HeatmapExportContext,
    InsightModel,
    SessionRecordingType,
} from '~/types'

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
    notebook?: NotebookType
    /**
     * Pre-serialized saved insights referenced by a shared notebook, keyed by `short_id`.
     * Each entry already includes computed `result`/`last_refresh`/etc. so the frontend can seed
     * `cachedInsight` + `cachedResults` and avoid POSTing to `/api/projects/.../query/` (which
     * `SharingAccessTokenAuthentication` rejects).
     */
    insights?: Record<string, InsightModel>
    /**
     * Pre-computed results for inline (non-saved-insight) ph-query nodes in a shared notebook,
     * keyed by node `nodeId`. Same rationale as `insights` — lets the shared viewer render
     * `<Query cachedResults={…} />` without ever hitting the query API.
     */
    inline_query_results?: Record<string, AnyResponseType>
    autoplay?: boolean
    /** Player adds border by default - we want to remove it **/
    noBorder?: boolean
    mode?: SessionRecordingPlayerMode
    exportToken?: string
    heatmap_url?: string
    heatmap_context?: HeatmapExportContext
    /** Cohort id+name inlined for shared views, which can't reach /api/cohorts. */
    cohorts?: Pick<CohortType, 'id' | 'name'>[]
}
