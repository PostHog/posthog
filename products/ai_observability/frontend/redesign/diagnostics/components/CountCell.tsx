import { humanFriendlyNumber } from 'lib/utils/numbers'

export interface CountCellProps {
    value: number
}

export function CountCell({ value }: CountCellProps): JSX.Element {
    return (
        <span className="inline-flex flex-col items-end tabular-nums" translate="no">
            <span>{humanFriendlyNumber(value)}</span>
        </span>
    )
}
