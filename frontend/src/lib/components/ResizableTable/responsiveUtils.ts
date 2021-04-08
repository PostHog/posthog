import { responsiveMap } from 'antd/lib/_util/responsiveObserve'

const sidebarAndPaddingWidth = 176
const gridBasis = 24

export function getMinColumnWidth(breakpoint: number, windowWidth: number): number {
    return breakpoint < 768 ? windowWidth / 3 : windowWidth / gridBasis
}

export function getMaxColumnWidth(breakpoint: number, windowWidth: number): number {
    return breakpoint < 768 ? windowWidth : windowWidth / 2
}

export function getFullwidthColumnSize(span: number = 1, breakpoint: number): number {
    const { innerWidth: width } = window
    const minWidth = getMinColumnWidth(breakpoint, width)
    const columnWidth = Math.floor(((width - sidebarAndPaddingWidth) / gridBasis) * span)
    return Math.max(columnWidth, minWidth)
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
