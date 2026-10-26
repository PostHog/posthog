import './menu.css'

import * as React from 'react'

/** The label and muted second line of a described menu row. Internal to the menu and combobox items. */
export function MenuItemBody({
    children,
    description,
}: {
    children: React.ReactNode
    description: React.ReactNode
}): React.ReactElement {
    return (
        <span className="quill-menu-item__body">
            <span className="quill-menu-item__title">{children}</span>
            <span className="quill-menu-item__description">{description}</span>
        </span>
    )
}
