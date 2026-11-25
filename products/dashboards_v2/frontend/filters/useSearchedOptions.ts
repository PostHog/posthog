import { useEffect, useState } from 'react'

const SEARCH_DELAY_MS = 200

/**
 * The options `load` returns for `search`, fetched once typing pauses. A newer search cancels the one in flight, so
 * a slow answer never replaces a newer one. Left out, `load` is never called and there are no options.
 */
export function useSearchedOptions<Option>(
    load: ((search: string, signal: AbortSignal) => Promise<Option[]>) | undefined,
    search: string
): { options: Option[]; loading: boolean } {
    const [options, setOptions] = useState<Option[]>([])
    const [loading, setLoading] = useState(!!load)

    useEffect(() => {
        if (!load) {
            return
        }
        const controller = new AbortController()
        setLoading(true)
        const run = async (): Promise<void> => {
            let next: Option[] = []
            try {
                next = await load(search, controller.signal)
            } catch {
                if (controller.signal.aborted) {
                    return
                }
            }
            setOptions(next)
            setLoading(false)
        }
        const timer = setTimeout(() => void run(), SEARCH_DELAY_MS)
        return () => {
            clearTimeout(timer)
            controller.abort()
        }
    }, [load, search])

    return { options, loading }
}
