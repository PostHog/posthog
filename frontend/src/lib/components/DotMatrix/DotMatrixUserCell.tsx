import './DotMatrixUserCell.scss'

import type { ReactNode } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

interface DotMatrixUserCellItem {
    id: string
    name: string
    email?: string
}

interface DotMatrixUserCellProps<D extends DotMatrixUserCellItem> {
    persons: D[]
    renderTooltip?: (person: D) => ReactNode
}

export function DotMatrixUserCell<D extends DotMatrixUserCellItem>({
    persons,
    renderTooltip,
}: DotMatrixUserCellProps<D>): JSX.Element {
    if (!persons.length) {
        return (
            <span className="DotMatrixUserCell__empty" aria-label="No users">
                ·
            </span>
        )
    }
    return (
        <div className="DotMatrixUserCell">
            {persons.slice(0, 3).map((person) => (
                <Tooltip
                    key={person.id}
                    className="DotMatrix__tooltip"
                    delayMs={100}
                    placement="bottom-start"
                    title={renderTooltip ? renderTooltip(person) : (person.email ?? person.name)}
                >
                    <span className="DotMatrixUserCell__name" tabIndex={0}>
                        {person.name}
                    </span>
                </Tooltip>
            ))}
            {persons.length > 3 && (
                <Tooltip
                    className="DotMatrix__tooltip"
                    title={
                        <div className="DotMatrixUserCell__all">
                            {persons.map((person) => (
                                <span key={person.id}>{person.email ?? person.name}</span>
                            ))}
                        </div>
                    }
                    delayMs={100}
                    openOnClick
                >
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        className="DotMatrixUserCell__more"
                        data-attr="dot-matrix-more-users"
                    >{`+${persons.length - 3} more`}</LemonButton>
                </Tooltip>
            )}
        </div>
    )
}
