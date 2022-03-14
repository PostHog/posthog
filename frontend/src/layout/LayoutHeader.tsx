import React from 'react'
import ReactDOM from 'react-dom'

const PAGE_HEADER_DIV_ID = 'page-header--portal'

export function LayoutHeader({ children }: { children: React.ReactChildren | React.ReactElement }): JSX.Element {
    const div = document.getElementById(PAGE_HEADER_DIV_ID)
    if (div) {
        return ReactDOM.createPortal(children, div)
    }
    return <></>
}

export function LayoutHeaderTarget(): JSX.Element {
    return <div id={PAGE_HEADER_DIV_ID} style={{ float: 'right' }} />
}
