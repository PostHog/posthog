import { useWindowSize } from 'lib/hooks/useWindowSize'
import { getBreakpoint } from 'lib/utils/responsiveUtils'

export function normalizeColumnTitle(title: string | JSX.Element): JSX.Element {
    return <span className="whitespace-nowrap">{title}</span>
}

// Returns a boolean indicating whether table should be scrolling or not given a specific
// breakpoint.
interface TableScrollProps {
    isTableScrolling: boolean
    tableScrollBreakpoint: number
    tableScrollX: number | string
}

export const useIsTableScrolling = (scrollBreakpoint: string): TableScrollProps => {
    const { width } = useWindowSize()
    const tableScrollBreakpoint = getBreakpoint(scrollBreakpoint)
    const isTableScrolling = !!width && width <= tableScrollBreakpoint

    return {
        isTableScrolling,
        tableScrollBreakpoint,
        tableScrollX: isTableScrolling ? 'max-content' : `${tableScrollBreakpoint}px`,
    }
}
