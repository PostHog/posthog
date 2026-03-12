import { useCallback, useSyncExternalStore } from 'react'

import { TAILWIND_BREAKPOINTS } from 'lib/constants'

type WindowSize = {
    width: number | undefined
    height: number | undefined
}

type Breakpoint = keyof typeof TAILWIND_BREAKPOINTS

type UseWindowSizeOptions = {
    /** Pixels to subtract from window width when checking breakpoints (e.g. side panel width) */
    widthOffset?: number
}

type UseWindowSize = {
    windowSize: WindowSize
    isWindowLessThan: (breakpoint: Breakpoint) => boolean
}

function subscribeToResize(callback: () => void): () => void {
    window.addEventListener('resize', callback)
    return () => window.removeEventListener('resize', callback)
}

let cachedSize: WindowSize = { width: undefined, height: undefined }

function getWindowSize(): WindowSize {
    const width = window.innerWidth
    const height = window.innerHeight
    if (cachedSize.width !== width || cachedSize.height !== height) {
        cachedSize = { width, height }
    }
    return cachedSize
}

const serverSnapshot: WindowSize = { width: undefined, height: undefined }

function getServerSnapshot(): WindowSize {
    return serverSnapshot
}

export function useWindowSize(options?: UseWindowSizeOptions): UseWindowSize {
    const windowSize = useSyncExternalStore(subscribeToResize, getWindowSize, getServerSnapshot)
    const widthOffset = options?.widthOffset ?? 0

    const isWindowLessThan = useCallback(
        (breakpoint: keyof typeof TAILWIND_BREAKPOINTS) =>
            !!windowSize?.width && windowSize.width - widthOffset < TAILWIND_BREAKPOINTS[breakpoint],
        [windowSize, widthOffset]
    )

    return { windowSize, isWindowLessThan }
}
