import { useCallback, useState } from 'react'

import { TAILWIND_BREAKPOINTS } from 'lib/constants'

import { useOnMountEffect } from './useOnMountEffect'

type WindowSize = {
    width: number | undefined
    height: number | undefined
}

type Breakpoint = keyof typeof TAILWIND_BREAKPOINTS

type UseWindowSize = {
    windowSize: WindowSize
    isWindowLessThan: (breakpoint: Breakpoint) => boolean
}

export function useWindowSize(): UseWindowSize {
    const isClient = typeof window === 'object'

    const getSize = useCallback(() => {
        return {
            width: isClient ? window.innerWidth : undefined,
            height: isClient ? window.innerHeight : undefined,
        }
    }, [isClient])

    const [windowSize, setWindowSize] = useState(getSize)

    const isWindowLessThan = useCallback(
        (breakpoint: keyof typeof TAILWIND_BREAKPOINTS) =>
            !!windowSize?.width && windowSize.width < TAILWIND_BREAKPOINTS[breakpoint],
        [windowSize]
    )

    useOnMountEffect(() => {
        if (!isClient) {
            return
        }

        function handleResize(): void {
            const size = getSize()
            setWindowSize(size)
        }

        window.addEventListener('resize', handleResize)
        return () => window.removeEventListener('resize', handleResize)
    })

    return { windowSize, isWindowLessThan }
}
