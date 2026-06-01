/**
 * Tiny label/value primitive shared by tool-call expansion bodies.
 */

interface LabeledProps {
    label: string
    children: React.ReactNode
}

export function Labeled({ label, children }: LabeledProps): React.ReactElement {
    return (
        <div>
            <div className="mb-1 text-[0.625rem] uppercase tracking-wide text-muted-foreground">{label}</div>
            {children}
        </div>
    )
}
