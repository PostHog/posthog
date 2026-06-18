import { TZLabel } from 'lib/components/TZLabel'

export function LastSavedIndicator({ timestamp }: { timestamp: string }): JSX.Element {
    return (
        <span className="text-xs text-tertiary">
            Last saved <TZLabel time={timestamp} />
        </span>
    )
}
