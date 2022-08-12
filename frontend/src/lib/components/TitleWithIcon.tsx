import React from 'react'

export interface TitleWithIconProps {
    icon: JSX.Element
    children: string | JSX.Element
    'data-attr'?: string
}

export function TitleWithIcon({ icon, children, 'data-attr': dataAttr }: TitleWithIconProps): JSX.Element {
    return (
        <div className="flex items-center" data-attr={dataAttr}>
            <div>{children}</div>
            <div className="title-icon">{icon}</div>
        </div>
    )
}
