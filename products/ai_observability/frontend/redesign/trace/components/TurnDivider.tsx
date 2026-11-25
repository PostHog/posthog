import { ShortTimestamp } from './ShortTimestamp'
import { formatSilence } from './turnGaps'

export interface TurnDividerProps {
    /** When the turn after the divider started, shown when it opens a day. */
    startedAt: string | null
    silenceMs: number | null
}

export function TurnDivider({ startedAt, silenceMs }: TurnDividerProps): JSX.Element {
    // Not a `separator`: that role hides its children from screen readers, and the text here is content.
    return (
        <div className="flex items-center gap-2 text-xs font-semibold text-tertiary">
            <span className="h-px flex-1 bg-border-primary" aria-hidden />
            {startedAt !== null ? <ShortTimestamp time={startedAt} /> : null}
            {startedAt !== null && silenceMs !== null ? <span aria-hidden>·</span> : null}
            {silenceMs !== null ? <span>{formatSilence(silenceMs)}</span> : null}
            <span className="h-px flex-1 bg-border-primary" aria-hidden />
        </div>
    )
}
