import { ReactNode } from 'react'

export const ErrorFiltersRoot = ({ children }: { children: ReactNode }): JSX.Element => {
    return (
        <div className="space-y-1">
            <div className="flex gap-2 items-center">{children}</div>
        </div>
    )
}
