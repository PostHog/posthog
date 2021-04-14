import { responsiveMap } from 'antd/lib/_util/responsiveObserve'

const gridBasis = 24

export function getMinColumnWidth(breakpoint: number): number {
    return breakpoint < 768 ? 40 : 50
}

export function getMaxColumnWidth(breakpoint: number): number {
    return breakpoint < 768 ? 500 : 750
}

export function getFullwidthColumnSize({
    wrapperWidth = 1200,
    breakpoint = 1600,
    useMinWidth = true,
}: {
    wrapperWidth?: number
    breakpoint?: number
    useMinWidth?: boolean
}): number {
    const columnWidth = Math.floor(wrapperWidth / gridBasis)
    if (!useMinWidth) {
        return columnWidth
    }
    const minWidth = getMinColumnWidth(breakpoint)
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
