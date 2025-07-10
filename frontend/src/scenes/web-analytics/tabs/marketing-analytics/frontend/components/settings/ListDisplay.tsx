import './ListDisplay.scss'

import { Tooltip } from '@posthog/lemon-ui'

interface ListDisplayProps {
    list: string[]
}

export const ListDisplay = ({ list }: ListDisplayProps): JSX.Element => {
    if (list.length === 0) {
        return <span className="text-muted">-</span>
    }

    const joinedList = list.join(', ')

    return (
        <Tooltip title={joinedList}>
            <div className="text-muted ListDisplay--truncated text-sm leading-tight">{joinedList}</div>
        </Tooltip>
    )
}
