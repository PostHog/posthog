import { CountCell } from '../CountCell'
import { DotMatrixUserCell } from '../DotMatrixUserCell'
import type { DotMatrixAxisItem, DotMatrixCell } from '../types'
import type { DotMatrixDemoMode } from './dotMatrixDemoLogic'
import { DotMatrixDemoUserTooltip } from './DotMatrixDemoUserTooltip'
import {
    DOT_MATRIX_MOCK_PRODUCTS,
    DOT_MATRIX_PRODUCT_COUNT_SCALE,
    DOT_MATRIX_USER_COUNT_SCALE,
} from './dotMatrixMockFixtures'
import { type DotMatrixMockDatum } from './dotMatrixMockTypes'

interface DotMatrixDemoDetailCellProps {
    cell: DotMatrixCell<DotMatrixMockDatum>
    row?: DotMatrixAxisItem
    mode: DotMatrixDemoMode
    selectedSeries: string[]
}

export function DotMatrixDemoDetailCell({
    cell,
    row,
    mode,
    selectedSeries,
}: DotMatrixDemoDetailCellProps): JSX.Element | null {
    if (row?.group === 'family') {
        return null
    }
    if (mode === 'users' && row?.group !== 'account') {
        const product = DOT_MATRIX_MOCK_PRODUCTS.find(([key]) => key === cell.rowKey.split('/')[1])?.[1] ?? ''
        return (
            <DotMatrixUserCell
                persons={cell.data[0]?.persons ?? []}
                renderTooltip={(person) => (
                    <DotMatrixDemoUserTooltip person={person} product={product} week={cell.columnKey} />
                )}
            />
        )
    }
    return (
        <CountCell
            size={mode === 'account' ? 'small' : 'xsmall'}
            value={cell.data[0]?.value ?? 0}
            scale={
                row?.group === 'summary' || (row?.group === 'account' && !selectedSeries.length)
                    ? DOT_MATRIX_PRODUCT_COUNT_SCALE
                    : DOT_MATRIX_USER_COUNT_SCALE
            }
        />
    )
}
