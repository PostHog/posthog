import './ListDisplay.scss'

import { Tooltip } from '@posthog/lemon-ui'

interface ListDisplayProps {
    list: string[]
}

export const ListDisplay = ({ list }: ListDisplayProps): JSX.Element => {
    if (list.length === 0) {
        return <span className="text-muted-foreground">-</span>
    }

    const joinedList = list.join(', ')

    return (
        <Tooltip title={joinedList}>
            <div className="text-muted-foreground text-sm leading-tight ListDisplay--truncated">{joinedList}</div>
        </Tooltip>
    )
}
