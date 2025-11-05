import throttle from 'lodash.throttle'
import { useCallback, useState } from 'react'

type AsyncCallbackType<U, T extends (...args: any[]) => Promise<U>> = (...args: Parameters<T>) => void

type AsyncCallbackOptions = {
    delay?: number
    leading?: boolean
    trailing?: boolean
}

export function useAsyncCallback<U, T extends (...args: any[]) => Promise<U>>(
    callback: T,
    deps: React.DependencyList = [],
    options: AsyncCallbackOptions = { delay: 0, leading: true }
): [(...args: Parameters<T>) => void, boolean, Error | null] {
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<Error | null>(null)

    const execute = useCallback(
        throttle(
            async (...args: Parameters<T>): Promise<U | undefined> => {
                setLoading(true)
                setError(null)
                try {
                    return await callback(...args)
                } catch (err) {
                    console.error(err)
                    setError(err as Error)
                } finally {
                    setLoading(false)
                }
            },
            options.delay,
            { leading: options.leading, trailing: options.trailing }
        ),
        [...deps, options.delay, options.leading, options.trailing]
    ) as unknown as AsyncCallbackType<U, T>

    return [execute, loading, error]
}
