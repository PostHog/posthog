import React from 'react'

export const FiltersRoot = ({ children }: { children: React.ReactNode }): JSX.Element => {
    return <div className="flex flex-wrap gap-2">{children}</div>
}
