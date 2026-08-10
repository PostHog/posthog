import { cn } from 'lib/utils/css-classes'

/**
 * The container a self-driving report sits in, wherever it appears next to the thing it came from.
 *
 * It is deliberately not a message bubble, and it is marked down its edge, so it never reads as
 * something a person said. The edge is a pseudo-element so it can run the full height without fighting
 * the border radius the way a left border does. It carries the AI colour, the same one the assistant's
 * own notes wear, so everything our software leaves on a record reads as one voice.
 *
 * Padding and inner layout come from `className`, because a chat thread and a side panel give a report
 * different room.
 */
export function SignalReportCard({
    className,
    children,
}: {
    className?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div
            className={cn(
                "relative overflow-hidden rounded border border-primary bg-surface-primary transition-colors hover:border-secondary after:content-[''] after:absolute after:inset-y-0 after:left-0 after:w-1 after:bg-ai",
                className
            )}
        >
            {children}
        </div>
    )
}
