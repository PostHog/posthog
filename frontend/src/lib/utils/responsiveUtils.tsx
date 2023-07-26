import useResponsiveObserver, { BreakpointMap } from 'antd/lib/_util/responsiveObserver'
import { ANTD_EXPAND_BUTTON_WIDTH } from '../components/ResizableTable'
import { useMemo } from 'react'

const getBreakpointMap = (responsiveMap: BreakpointMap): { [k: string]: number } =>
    Object.fromEntries(Object.entries(responsiveMap).map(([key, cssStatement]) => [key, parsePixelValue(cssStatement)]))

const getBreakpointValues = (responsiveMap: BreakpointMap): number[] =>
    Object.values(getBreakpointMap(responsiveMap)).sort((a, b) => a - b)

export function getMinColumnWidth(breakpoint: number): number {
    return breakpoint < 576 ? 150 : 50
}

export function getFullwidthColumnSize(wrapperWidth: number = 1200, gridBasis = 24): number {
    const innerWidth = wrapperWidth - ANTD_EXPAND_BUTTON_WIDTH
    return Math.floor(innerWidth / gridBasis)
}

export function parsePixelValue(cssStatement: string): number {
    return parseFloat(cssStatement.replace(/[^\d.]/g, ''))
}

export function useActiveBreakpointValue(): number {
    const { responsiveMap } = useResponsiveObserver()
    const breakpointValues = useMemo(() => getBreakpointValues(responsiveMap), [responsiveMap])
    const windowWidth = window.innerWidth
    const lastMatchingBreakpoint = breakpointValues.filter((value) => windowWidth >= value).pop()
    return lastMatchingBreakpoint || breakpointValues[0]
}

export function useBreakpointValue(breakpointKey: string): number {
    const { responsiveMap } = useResponsiveObserver()
    const map = useMemo(() => getBreakpointMap(responsiveMap), [responsiveMap])
    return map[breakpointKey] || -1
}
