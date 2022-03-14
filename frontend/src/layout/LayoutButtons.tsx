import React from 'react'
import ReactDOM from 'react-dom'

const PAGE_BUTTONS_DIV_ID = 'page-buttons--portal'

export function LayoutButtons({ children }: { children: React.ReactChildren | React.ReactElement }): JSX.Element {
    const div = document.getElementById(PAGE_BUTTONS_DIV_ID)
    if (div) {
        return ReactDOM.createPortal(children, div)
    }
    return <></>
}

export function LayoutButtonsTarget(): JSX.Element {
    return <div id={PAGE_BUTTONS_DIV_ID} style={{ float: 'right' }} />
}
