import { useEffect, useRef, useState } from 'react'

// The lookups ported from Dash were written against TanStack Query. This keeps their call shape on plain React state,
// so they run on sample data today and can move to kea loaders on real endpoints without touching every caller.
export const keepPreviousData = Symbol('keepPreviousData')

export interface QueryOptions<T> {
    queryKey: readonly unknown[]
    queryFn: (context: { signal: AbortSignal; queryKey: readonly unknown[] }) => Promise<T> | T
    enabled?: boolean
    staleTime?: number
    placeholderData?: typeof keepPreviousData | T
    refetchInterval?: number | false
}

export interface QueryResult<T> {
    data: T | undefined
    error: Error | null
    isLoading: boolean
    isFetching: boolean
    isSuccess: boolean
    isError: boolean
    isPlaceholderData: boolean
    refetch: () => void
}

const cache = new Map<string, unknown>()

export function useQuery<T>(options: QueryOptions<T>): QueryResult<T> {
    const key = JSON.stringify(options.queryKey)
    const enabled = options.enabled !== false
    const [state, setState] = useState<{ key: string; data?: T; error: Error | null; fetching: boolean }>(() => ({
        key,
        data: cache.get(key) as T | undefined,
        error: null,
        fetching: enabled && !cache.has(key),
    }))
    const [attempt, setAttempt] = useState(0)
    const latest = useRef(options)
    latest.current = options

    useEffect(() => {
        if (!enabled) {
            return
        }
        const controller = new AbortController()
        const keepPrevious = latest.current.placeholderData === keepPreviousData
        setState((previous) => ({
            key,
            data: cache.has(key) ? (cache.get(key) as T) : keepPrevious ? previous.data : undefined,
            error: null,
            fetching: true,
        }))
        Promise.resolve()
            .then(() => latest.current.queryFn({ signal: controller.signal, queryKey: latest.current.queryKey }))
            .then((data) => {
                if (!controller.signal.aborted) {
                    cache.set(key, data)
                    setState({ key, data, error: null, fetching: false })
                }
            })
            .catch((error: Error) => {
                if (!controller.signal.aborted) {
                    setState((previous) => ({ ...previous, key, error, fetching: false }))
                }
            })
        return () => controller.abort()
    }, [key, enabled, attempt])

    const current = state.key === key
    const settled = current && !state.fetching
    const keepPrevious = options.placeholderData === keepPreviousData
    const placeholder =
        options.placeholderData !== undefined && !keepPrevious ? (options.placeholderData as T) : undefined
    const own = current || (keepPrevious && enabled) ? state.data : (cache.get(key) as T | undefined)
    const data = own ?? placeholder
    return {
        data,
        error: state.error,
        isLoading: enabled && data === undefined && !state.error,
        isFetching: enabled && !settled,
        isSuccess: settled && !state.error && own !== undefined,
        isError: !!state.error,
        isPlaceholderData: !settled && data !== undefined,
        refetch: () => {
            cache.delete(key)
            setAttempt((count) => count + 1)
        },
    }
}

export function useQueries<T>({ queries }: { queries: QueryOptions<T>[] }): QueryResult<T>[] {
    const key = JSON.stringify(queries.map((query) => query.queryKey))
    const combined = useQuery<(T | undefined)[]>({
        queryKey: ['useQueries', key],
        queryFn: ({ signal }) =>
            Promise.all(
                queries.map((query) =>
                    query.enabled === false ? undefined : query.queryFn({ signal, queryKey: query.queryKey })
                )
            ),
    })
    return queries.map((_, index) => ({
        ...combined,
        data: combined.data?.[index],
    }))
}

export function useQueryClient(): {
    getQueryData: <T>(queryKey: readonly unknown[]) => T | undefined
    setQueryData: <T>(queryKey: readonly unknown[], data: T) => void
    invalidateQueries: (filter?: { queryKey?: readonly unknown[] }) => void
} {
    return {
        getQueryData: <T>(queryKey: readonly unknown[]) => cache.get(JSON.stringify(queryKey)) as T | undefined,
        setQueryData: <T>(queryKey: readonly unknown[], data: T) => void cache.set(JSON.stringify(queryKey), data),
        invalidateQueries: (filter): void => {
            const prefix = filter?.queryKey ? JSON.stringify(filter.queryKey).slice(0, -1) : ''
            for (const key of cache.keys()) {
                if (key.startsWith(prefix)) {
                    cache.delete(key)
                }
            }
        },
    }
}
