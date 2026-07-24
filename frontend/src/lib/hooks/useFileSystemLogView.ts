import { useEffect } from 'react'

import api, { ApiConfig } from 'lib/api'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { recentItemsModel } from '~/models/recentItemsModel'

type FileSystemLogViewType =
    | 'experiment'
    | 'feature_flag'
    | 'insight'
    | 'dashboard'
    | 'scene'
    | 'action'
    | 'cohort'
    | 'survey'
    | 'early_access_feature'
    | 'link'
    | 'notebook'
    | 'session_recording_playlist'
    | `hog_function/${string}`

interface TrackFileSystemLogViewOptions {
    type: FileSystemLogViewType
    ref: string | number | null | undefined
    enabled?: boolean
}

export function trackFileSystemLogView({ type, ref, enabled = true }: TrackFileSystemLogViewOptions): void {
    if (
        !enabled ||
        window.IMPERSONATED_SESSION ||
        isSharedView() ||
        ref === null ||
        ref === undefined ||
        !ApiConfig.hasCurrentTeamId()
    ) {
        return
    }

    recentItemsModel.findMounted()?.actions.recordView(type, String(ref))
    // Best-effort recent-items tracking: swallow failures (including 404s when the path isn't
    // routed for this team) so a fire-and-forget POST never becomes an uncaught rejection that
    // spams error tracking.
    void api.fileSystemLogView.create({ type, ref: String(ref) }).catch(() => {})
}

export function useFileSystemLogView({ type, ref, enabled = true }: TrackFileSystemLogViewOptions): void {
    useEffect(() => {
        trackFileSystemLogView({ type, ref, enabled })
    }, [type, ref, enabled])
}
