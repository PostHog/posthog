import { useCallback } from 'react'

import { defaultResolveValue } from '../types'
import type { ResolveValueFn } from '../types'
import { useLatest } from './useLatest'

export function useStableResolveValue(resolveValue: ResolveValueFn | undefined): ResolveValueFn {
    const ref = useLatest(resolveValue)
    return useCallback<ResolveValueFn>((s, i) => (ref.current ?? defaultResolveValue)(s, i), [ref])
}
