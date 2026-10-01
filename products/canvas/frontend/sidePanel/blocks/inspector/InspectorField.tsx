import { ReactNode } from 'react'

/** A labeled inspector control, with an optional hint under it. */
export function InspectorField({
    label,
    hint,
    children,
}: {
    label: string
    hint?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <div className="text-xs font-medium text-muted-foreground">{label}</div>
            {children}
            {hint ? <div className="text-xs leading-snug text-muted-foreground">{hint}</div> : null}
        </div>
    )
}
