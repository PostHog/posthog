import { ReactNode } from 'react'

export const FiltersRoot = ({ children }: { children: ReactNode }): JSX.Element => {
    return <div className="flex flex-wrap gap-2">{children}</div>
}
