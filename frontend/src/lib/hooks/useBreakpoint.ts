import { useEffect, useState } from 'react'
import { useWindowSize } from './useWindowSize'
import { getActiveBreakpoint } from 'lib/utils/responsiveUtils'

export const useBreakpoint = (): number => {
    const { width } = useWindowSize()
    const [breakpoint, setBreakpoint] = useState(getActiveBreakpoint)

    useEffect(() => {
        setBreakpoint(getActiveBreakpoint)
    }, [width])

    return breakpoint
}
