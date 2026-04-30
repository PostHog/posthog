import { useCallback, useRef } from 'react'

import type { ResolveValueFn } from '../types'

// Stable identity over a possibly-changing fn so callers don't have to memoize the prop.
export function useStableResolveValue(resolveValue: ResolveValueFn | undefined): ResolveValueFn {
    const ref = useRef<ResolveValueFn | undefined>(resolveValue)
    ref.current = resolveValue
    return useCallback<ResolveValueFn>((s, i) => {
        const fn = ref.current
        if (fn) {
            return fn(s, i)
        }
        const v = s.data[i]
        return typeof v === 'number' && Number.isFinite(v) ? v : 0
    }, [])
}
