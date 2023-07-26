import { useEffect, useState } from 'react'
import { useWindowSize } from './useWindowSize'
import { useActiveBreakpointValue } from 'lib/utils/responsiveUtils'

export const useBreakpoint = (): number => {
    const activeBreakpoint = useActiveBreakpointValue()
    const { width } = useWindowSize()
    const [breakpoint, setBreakpoint] = useState(activeBreakpoint)

    useEffect(() => {
        setBreakpoint(activeBreakpoint)
    }, [width])

    return breakpoint
}
