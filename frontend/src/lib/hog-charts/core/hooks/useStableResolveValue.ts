import { useCallback } from 'react'

import type { ResolveValueFn } from '../types'
import { useLatest } from './useLatest'

export function useStableResolveValue(resolveValue: ResolveValueFn | undefined): ResolveValueFn {
    const ref = useLatest(resolveValue)
    return useCallback<ResolveValueFn>(
        (s, i) => {
            const fn = ref.current
            if (fn) {
                return fn(s, i)
            }
            const v = s.data[i]
            return typeof v === 'number' && Number.isFinite(v) ? v : 0
        },
        [ref]
    )
}
