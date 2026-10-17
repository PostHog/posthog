import { useEffect } from 'react'

import api, { ApiConfig } from 'lib/api'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { recentItemsModel } from '~/models/recentItemsModel'

export type FileSystemLogViewType =
    | 'experiment'
    | 'feature_flag'
    | 'insight'
    | 'dashboard'
    | 'scene'
    | 'canvas'
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

    const model = recentItemsModel.findMounted()
    model?.actions.recordView(type, String(ref))
    // Fire-and-forget view tracking: a failure must not surface as an unhandled rejection.
    api.fileSystemLogView
        .create({ type, ref: String(ref) })
        .then(() => model?.actions.viewLogged(type, String(ref)))
        .catch(() => {})
}

export function useFileSystemLogView({ type, ref, enabled = true }: TrackFileSystemLogViewOptions): void {
    useEffect(() => {
        trackFileSystemLogView({ type, ref, enabled })
    }, [type, ref, enabled])
}
