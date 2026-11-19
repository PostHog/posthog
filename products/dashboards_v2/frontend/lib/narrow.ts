import { useEffect, useState, useSyncExternalStore } from 'react'

const subscribers = new Map<string, (cb: () => void) => () => void>()
function useMedia(query: string): boolean {
    let subscribe = subscribers.get(query)
    if (!subscribe) {
        subscribe = (cb) => {
            const m = matchMedia(query)
            m.addEventListener('change', cb)
            return () => m.removeEventListener('change', cb)
        }
        subscribers.set(query, subscribe)
    }
    return useSyncExternalStore(subscribe, () => matchMedia(query).matches)
}

export const useNarrow = (): boolean => useMedia('(max-width: 767px)')
export const useWide = (): boolean => useMedia('(min-width: 1536px)')
export const useLarge = (): boolean => useMedia('(min-width: 1024px)')

export function useVisibleViewport(on: boolean): { top: number; height: number } | undefined {
    const [v, setV] = useState<{ top: number; height: number }>()
    useEffect(() => {
        const vv = window.visualViewport
        if (!on || !vv) {
            return setV(undefined)
        }
        const update = (): void => setV({ top: vv.offsetTop, height: vv.height })
        update()
        vv.addEventListener('resize', update)
        vv.addEventListener('scroll', update)
        return () => {
            vv.removeEventListener('resize', update)
            vv.removeEventListener('scroll', update)
        }
    }, [on])
    return v
}
