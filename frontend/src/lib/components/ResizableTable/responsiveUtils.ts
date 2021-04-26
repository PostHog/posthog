import { responsiveMap } from 'antd/lib/_util/responsiveObserve'

const gridBasis = 24

export function getMinColumnWidth(breakpoint: number): number {
    return breakpoint < 768 ? 40 : 50
}

export function getMaxColumnWidth(breakpoint: number): number {
    return breakpoint < 768 ? 500 : 750
}

export function getFullwidthColumnSize(wrapperWidth: number = 1200): number {
    return Math.floor(wrapperWidth / gridBasis)
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
