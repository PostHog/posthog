import { isSendingStopped } from './emailSenderFields'

export function SenderOptionLabel({ label, sender }: { label: string; sender: { config?: unknown } }): JSX.Element {
    if (!isSendingStopped(sender)) {
        return <>{label}</>
    }
    return (
        <span className="flex min-w-0 items-center gap-2">
            <span className="truncate">{label}</span>
            <span className="shrink-0 text-xs text-danger">Sending stopped</span>
        </span>
    )
}
