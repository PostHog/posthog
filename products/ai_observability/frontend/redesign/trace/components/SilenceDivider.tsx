import { formatSilence } from './turnGaps'

export interface SilenceDividerProps {
    silenceMs: number
}

export function SilenceDivider({ silenceMs }: SilenceDividerProps): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-xs font-semibold text-tertiary" role="separator">
            <span className="h-px flex-1 bg-border-primary" />
            {formatSilence(silenceMs)}
            <span className="h-px flex-1 bg-border-primary" />
        </div>
    )
}
