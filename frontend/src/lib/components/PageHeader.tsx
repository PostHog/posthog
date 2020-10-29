import React from 'react'

interface PageHeaderProps {
    title: string | JSX.Element
    caption?: string | JSX.Element
}

export function PageHeader({ title, caption }: PageHeaderProps): JSX.Element {
    return (
        <>
            <h1 className="page-title">{title}</h1>
            {caption && <div className="page-caption">{caption}</div>}
        </>
    )
}
