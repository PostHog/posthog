import { ReactNode } from 'react'

export function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h3 className="mb-0">{title}</h3>
            {children}
        </div>
    )
}
