import React, { useEffect, useState } from 'react'
import useSize from '@react-hook/size'

interface BreakpointMap {
    width: number // breakpoint width
    value: any
}

/**
 * Get the value associated with the current active breakpoint. The largest width that satisfies width >= currentWidth will be selected
 *
 * @param breakpointMap array of breakpoint widths and corresponding values to return
 * @param target element to listen to width changes
 */
export function useResponsiveWidth(target: React.RefObject<any> | null, breakpointMap: BreakpointMap[]): any {
    const [currentWidth] = useSize(target)
    const [value, setValue] = useState(null)

    const findBinValue = (): void => {
        if (breakpointMap.length === 0) {
            return
        }
        for (const { width, value: _value } of breakpointMap.slice().reverse()) {
            console.log('width', width, 'currentwidth', currentWidth)
            if (currentWidth >= width) {
                console.log('setting valu', _value, width, currentWidth)
                setValue(_value)
                return
            }
        }
        setValue(breakpointMap[0].value) // return first value
    }

    useEffect(() => {
        if (target?.current) {
            findBinValue()
        }
    }, [currentWidth, target?.current])

    return value
}
