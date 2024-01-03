import { getActiveBreakpointValue } from 'lib/utils/responsiveUtils'
import { useEffect, useState } from 'react'

import { useWindowSize } from './useWindowSize'

export const useBreakpoint = (): number => {
    const { width } = useWindowSize()
    const [breakpoint, setBreakpoint] = useState(getActiveBreakpointValue)

    useEffect(() => {
        setBreakpoint(getActiveBreakpointValue)
    }, [width])

    return breakpoint
}
