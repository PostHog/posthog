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
    | 'canvas'
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

    const recents = recentItemsModel.findMounted()
    // A listed item moves to the top locally, and scene views feed a separate list. Any other item has no row to
    // move, so the list reads again once the server has recorded this view.
    const needsReload =
        type !== 'scene' && !recents?.values.recents.some((entry) => entry.type === type && entry.ref === String(ref))
    recents?.actions.recordView(type, String(ref))
    // Fire-and-forget view tracking: a failure must not surface as an unhandled rejection.
    api.fileSystemLogView
        .create({ type, ref: String(ref) })
        .then(() => {
            if (needsReload) {
                recents?.actions.loadRecents()
            }
        })
        .catch(() => {})
}

export function useFileSystemLogView({ type, ref, enabled = true }: TrackFileSystemLogViewOptions): void {
    useEffect(() => {
        trackFileSystemLogView({ type, ref, enabled })
    }, [type, ref, enabled])
}
