import { DependencyList, useEffect } from 'react'

import api from 'lib/api'

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

export interface UseFileSystemLogViewOptions extends TrackFileSystemLogViewOptions {
    deps: DependencyList
}

export function trackFileSystemLogView({ type, ref, enabled = true }: TrackFileSystemLogViewOptions): void {
    if (!enabled || window.IMPERSONATED_SESSION || ref === null || ref === undefined) {
        return
    }

    void api.fileSystemLogView.create({ type, ref: String(ref) })
}

export function useFileSystemLogView({ deps, ...options }: UseFileSystemLogViewOptions): void {
    useEffect(() => {
        trackFileSystemLogView(options)
    }, deps)
}
