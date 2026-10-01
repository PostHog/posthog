import { ReactNode } from 'react'

/** An explanation in place of settings, for blocks and elements the inspector cannot change. */
export function ControlNote({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="rounded-md bg-fill-hover px-2.5 py-2 text-xs leading-snug text-muted-foreground">
            {children}
        </div>
    )
}
