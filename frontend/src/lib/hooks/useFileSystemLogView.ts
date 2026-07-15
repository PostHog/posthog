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

    // Scene-view tracking is best-effort telemetry. hasCurrentTeamId() alone isn't a reliable guard
    // in every bundle context: the toolbar swaps lib/api for an inert proxy whose methods return
    // truthy stand-ins, so a missing team ID can slip past the check and the team-scoped request
    // throws synchronously ("Team ID is not known."). A view we fail to record must never crash the page.
    try {
        recentItemsModel.findMounted()?.actions.recordView(type, String(ref))
        void api.fileSystemLogView.create({ type, ref: String(ref) })
    } catch {
        // best-effort: swallow so tracking failures never surface as uncaught exceptions
    }
}

export function useFileSystemLogView({ type, ref, enabled = true }: TrackFileSystemLogViewOptions): void {
    useEffect(() => {
        trackFileSystemLogView({ type, ref, enabled })
    }, [type, ref, enabled])
}
