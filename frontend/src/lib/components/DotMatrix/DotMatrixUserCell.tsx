import './DotMatrixUserCell.scss'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { getDotMatrixMockWeekLabel, type DotMatrixMockPerson } from './mocks'

interface DotMatrixUserCellProps {
    persons: DotMatrixMockPerson[]
    product: string
    week: string
}

export function DotMatrixUserCell({ persons, product, week }: DotMatrixUserCellProps): JSX.Element {
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
                    title={
                        <div className="DotMatrixUserCell__tooltip">
                            <div className="DotMatrixUserCell__title">
                                <strong>{person.email}</strong>
                                <span className="text-muted">{`${product} · ${getDotMatrixMockWeekLabel(week)}`}</span>
                            </div>
                            <div className="DotMatrixUserCell__detail">
                                <span>{`Time on ${product} pages`}</span>
                                <b>{`${Math.floor(person.seconds / 60)}m ${String(person.seconds % 60).padStart(2, '0')}s`}</b>
                            </div>
                            <div className="DotMatrixUserCell__pages">
                                <span className="DotMatrixUserCell__section">Top pages by time</span>
                                <div className="DotMatrixUserCell__detail font-mono text-xs">
                                    <span>/insights/new</span>
                                    <b>6m 10s</b>
                                </div>
                                <div className="DotMatrixUserCell__detail font-mono text-xs">
                                    <span>/dashboard/42</span>
                                    <b>4m 05s</b>
                                </div>
                                <div className="DotMatrixUserCell__detail font-mono text-xs">
                                    <span>/insights/aB3xQ9</span>
                                    <b>2m 51s</b>
                                </div>
                            </div>
                            <div className="DotMatrixUserCell__detail DotMatrixUserCell__action">
                                <span>insight created</span>
                                <b>×3</b>
                            </div>
                            <div className="DotMatrixUserCell__detail DotMatrixUserCell__action">
                                <span>dashboard updated</span>
                                <b>×1</b>
                            </div>
                        </div>
                    }
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
                                <span key={person.id}>{person.email}</span>
                            ))}
                        </div>
                    }
                    delayMs={100}
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
