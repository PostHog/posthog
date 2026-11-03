import './DotMatrixDemoTooltip.scss'

import { getDotMatrixMockWeekLabel, DOT_MATRIX_MOCK_PRODUCTS, type DotMatrixMockDatum } from './mocks'
import type { DotMatrixCell } from './types'

interface DotMatrixDemoAccountTooltipProps {
    cell: DotMatrixCell<DotMatrixMockDatum>
}

export function DotMatrixDemoAccountTooltip({ cell }: DotMatrixDemoAccountTooltipProps): JSX.Element {
    const datum = cell.data[0]
    const product = DOT_MATRIX_MOCK_PRODUCTS.find(([key]) => key === cell.rowKey.split('/')[1])?.[1] ?? 'Products used'
    const durations = ['14m 32s', '11m 05s', '9m 40s', '6m 12s', '4m 58s']
    const actions = ['4 actions', '2 actions', '6 actions', '1 action', '']
    const persons = datum?.persons ?? []
    return (
        <div className="DotMatrixDemo__account-tooltip">
            <strong>{`${product} · ${datum?.value ?? 0} users`}</strong>
            <span className="text-muted">{getDotMatrixMockWeekLabel(cell.columnKey)}</span>
            {persons.slice(0, 5).map((person, index) => (
                <div className="DotMatrixDemo__tooltip-line" key={person.id}>
                    <span>{person.name}</span>
                    <span className="text-secondary">{`${durations[index]}${actions[index] ? ` · ${actions[index]}` : ''}`}</span>
                </div>
            ))}
            {persons.length > 5 && <span className="text-link">{`+${persons.length - 5} more`}</span>}
        </div>
    )
}
