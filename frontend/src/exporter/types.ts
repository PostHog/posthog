import { NotebookType } from 'scenes/notebooks/types'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { AnyResponseType, QuerySchema, SharingConfigurationSettings } from '~/queries/schema/schema-general'
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
    Interview = 'interview',
}

export interface InterviewExportPayload {
    topic_id: string
    interviewee_identifier: string
    user_name: string
    topic: string
    already_replied: boolean
    /**
     * True for a non-personalised (shared) topic link, where every visitor is a new anonymous
     * respondent who self-identifies with a name before starting. False for a personalised
     * per-invitee link (which greets a known `user_name`).
     */
    shared: boolean
    /**
     * NOTE: `agent_context`, `questions`, and the Vapi credentials are intentionally NOT in
     * this payload. They live behind `POST /api/user_interviews/share/<token>/start_call/`
     * so the personalized agent context never lands in the public HTML.
     */
}

/** A publicly shared desktop canvas: the published build renders in a sandboxed iframe. */
export interface SharedCanvasPayload {
    id: string
    name: string
    kind: 'freeform' | 'grid' | 'component'
    description: string
    /** Whether the canvas has a live build. False leaves `artifact_url` null. */
    published: boolean
    /**
     * Signed URL of the published build's entry HTML, minted for this page load. Null until the
     * canvas is published, or when artifact delivery is not configured on this instance.
     */
    artifact_url: string | null
    /** Whether the owner lets anyone with the link copy the canvas into their own project. */
    allow_forking: boolean
}

/** A publicly shared file a task run produced. The share follows the file, so this is its newest version. */
export interface SharedTaskArtifactPayload {
    name: string
    content_type: string
    /** Decides the renderer: markdown inline, images inline, everything else a download. */
    kind: 'markdown' | 'image' | 'html' | 'file'
    size: number | null
    uploaded_at: string | null
    /** The markdown text, inlined when the file is small enough to ship in the page. */
    markdown: string | null
    /** Same-token file URL: renders inline for images, downloads for everything else. */
    file_url: string
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
    /**
     * Ad-hoc query for an insight-less image export (`export_context.source`), with its
     * pre-computed result in `query_results` — same rationale as `inline_query_results`.
     */
    query?: QuerySchema
    query_results?: AnyResponseType
    /** Optional title shown inside an ad-hoc query image export. */
    query_title?: string
    autoplay?: boolean
    /** Player adds border by default - we want to remove it **/
    noBorder?: boolean
    mode?: SessionRecordingPlayerMode
    exportToken?: string
    heatmap_url?: string
    heatmap_context?: HeatmapExportContext
    /** Cohort id+name inlined for shared views, which can't reach /api/cohorts. */
    cohorts?: Pick<CohortType, 'id' | 'name'>[]
    /** AI user interview payload — present only for `type === ExportType.Interview`. */
    interview?: InterviewExportPayload
    /** Shared desktop canvas payload. */
    canvas?: SharedCanvasPayload
    /** Shared task-run artifact payload. */
    task_artifact?: SharedTaskArtifactPayload
}
