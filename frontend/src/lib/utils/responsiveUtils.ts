import { responsiveMap } from 'antd/lib/_util/responsiveObserve'
import { ANTD_EXPAND_BUTTON_WIDTH } from '../components/ResizableTable'

const BREAKPOINT_MAP = Object.entries(responsiveMap).reduce<Record<string, number>>(
    (acc, [key, cssStatement]) => ({
        ...acc,
        [key]: parsePixelValue(cssStatement),
    }),
    {}
)
const BREAKPOINT_VALUES = Object.values(BREAKPOINT_MAP)

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

export function getActiveBreakpoint(): number {
    const { innerWidth: width } = window
    let breakpoint = BREAKPOINT_VALUES[0]
    BREAKPOINT_VALUES.forEach((value) => {
        if (width > breakpoint) {
            breakpoint = value
        }
    })
    return breakpoint
}

export function getBreakpoint(breakpointKey: string): number {
    return BREAKPOINT_MAP[breakpointKey] || -1
}
