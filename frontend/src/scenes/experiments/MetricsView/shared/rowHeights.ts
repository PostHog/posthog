import { CELL_HEIGHT } from '~/scenes/experiments/MetricsView/new/constants'

export const FIXED_HEIGHT_STYLE: React.CSSProperties = {
    height: `${CELL_HEIGHT}px`,
    maxHeight: `${CELL_HEIGHT}px`,
}

export const getScaledHeightStyle = (rowCount: number): React.CSSProperties => {
    const scaledHeight = `${CELL_HEIGHT * rowCount}px`
    return { height: scaledHeight, maxHeight: scaledHeight }
}

export const getMinHeightStyle = (height: number): React.CSSProperties => ({ minHeight: `${height}px` })
