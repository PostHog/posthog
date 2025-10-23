import { DependencyList, useEffect } from 'react'

import api from 'lib/api'

type FileSystemLogViewType = 'experiment' | 'feature_flag' | 'insight' | 'dashboard'

export interface UseFileSystemLogViewOptions {
    type: FileSystemLogViewType
    ref: string | number | null | undefined
    enabled?: boolean
    deps: DependencyList
}

export function useFileSystemLogView({ type, ref, enabled = true, deps }: UseFileSystemLogViewOptions): void {
    useEffect(() => {
        if (!enabled || ref === null || ref === undefined) {
            return
        }

        void api.fileSystemLogView.create({ type, ref: String(ref) })
    }, deps)
}
