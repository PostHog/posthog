import { DependencyList, useEffect } from 'react'

import api from 'lib/api'

export interface UseFileSystemLogViewOptions {
    type: 'experiment' | 'feature_flag'
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
