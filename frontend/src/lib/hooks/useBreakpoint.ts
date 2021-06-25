import { useEffect, useState } from 'react'
import { useWindowSize } from './useWindowSize'
import { getActiveBreakpointValue } from 'lib/utils/responsiveUtils'

export const useBreakpoint = (): number => {
    const { width } = useWindowSize()
    const [breakpoint, setBreakpoint] = useState(getActiveBreakpointValue)

    useEffect(() => {
        setBreakpoint(getActiveBreakpointValue)
    }, [width])

    return breakpoint
}
