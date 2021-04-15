import { responsiveMap } from 'antd/lib/_util/responsiveObserve'
import { ANTD_EXPAND_BUTTON_WIDTH } from './index'

export function getMinColumnWidth(breakpoint: number): number {
    return breakpoint < 576 ? 150 : 50
}

export function getFullwidthColumnSize(wrapperWidth: number = 1200, gridBasis = 24): number {
    const innerWidth = wrapperWidth - ANTD_EXPAND_BUTTON_WIDTH
    return Math.floor(innerWidth / gridBasis)
}

function getPixelValue(cssStatement: string): number {
    return parseInt(cssStatement.replace(/\D/g, ''), 10)
}

export function getActiveBreakpoint(): number {
    const { innerWidth: width } = window
    const breakpoints = Object.values(responsiveMap).map((cssStatement) => getPixelValue(cssStatement))
    let breakpoint = breakpoints[0]
    breakpoints.forEach((value) => {
        if (width > breakpoint) {
            breakpoint = value
        }
    })
    return breakpoint
}
