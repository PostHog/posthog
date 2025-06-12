import './ListDisplay.scss'

import { Tooltip } from '@posthog/lemon-ui'

interface ListDisplayProps {
    list: string[]
}

export const ListDisplay = ({ list }: ListDisplayProps): JSX.Element => {
    if (list.length === 0) {
        return <span className="text-muted">-</span>
    }

    const joinedlist = list.join(', ')

    return (
        <Tooltip title={joinedlist}>
            <div className="text-muted text-sm leading-tight ListDisplay--truncated">{joinedlist}</div>
        </Tooltip>
    )
}
