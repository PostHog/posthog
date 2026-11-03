import { getDotMatrixMockWeekLabel } from './dotMatrixMockFixtures'
import { type DotMatrixMockPerson } from './dotMatrixMockTypes'

interface DotMatrixDemoUserTooltipProps {
    person: DotMatrixMockPerson
    product: string
    week: string
}

export function DotMatrixDemoUserTooltip({ person, product, week }: DotMatrixDemoUserTooltipProps): JSX.Element {
    return (
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
    )
}
