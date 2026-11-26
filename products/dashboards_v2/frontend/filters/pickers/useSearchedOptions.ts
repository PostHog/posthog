import { useCallback, useEffect, useState } from 'react'

const DEFAULT_SEARCH_DELAY_MS = 200
const DEFAULT_REFRESH_POLL_MS = 2000

/** Options a loader found. `refreshing` says they are cached and newer ones are on the way, so the search runs again. */
export type LoadedOptions<Option> = Option[] | { options: Option[]; refreshing: boolean }

export type OptionsLoader<Option> = (search: string, signal: AbortSignal) => Promise<LoadedOptions<Option>>

export type SearchTiming = {
    /** How long typing must pause before a search runs. */
    searchDelayMs?: number
    /** How long to wait before searching again while the loader reports `refreshing`. */
    refreshPollMs?: number
}

/**
 * The options `load` returns for `search`, fetched once typing pauses. A newer search cancels the one in flight, so
 * a slow answer never replaces a newer one. Left out, `load` is never called and there are no options.
 */
export function useSearchedOptions<Option>(
    load: OptionsLoader<Option> | undefined,
    search: string,
    { searchDelayMs = DEFAULT_SEARCH_DELAY_MS, refreshPollMs = DEFAULT_REFRESH_POLL_MS }: SearchTiming = {}
): { options: Option[]; loading: boolean; failed: boolean; retry: () => void } {
    const [options, setOptions] = useState<Option[]>([])
    const [loading, setLoading] = useState(!!load)
    const [failed, setFailed] = useState(false)
    const [attempt, setAttempt] = useState(0)

    useEffect(() => {
        if (!load) {
            return
        }
        const controller = new AbortController()
        let timer: ReturnType<typeof setTimeout>
        setLoading(true)
        setFailed(false)
        const run = async (): Promise<void> => {
            let loaded: LoadedOptions<Option>
            try {
                loaded = await load(search, controller.signal)
            } catch {
                if (!controller.signal.aborted) {
                    setFailed(true)
                    setLoading(false)
                }
                return
            }
            const refreshing = !Array.isArray(loaded) && loaded.refreshing
            setOptions(Array.isArray(loaded) ? loaded : loaded.options)
            setLoading(false)
            if (refreshing) {
                timer = setTimeout(() => void run(), refreshPollMs)
            }
        }
        timer = setTimeout(() => void run(), searchDelayMs)
        return () => {
            clearTimeout(timer)
            controller.abort()
        }
    }, [load, search, attempt, searchDelayMs, refreshPollMs])

    const retry = useCallback(() => setAttempt((count) => count + 1), [])
    return { options, loading, failed, retry }
}
