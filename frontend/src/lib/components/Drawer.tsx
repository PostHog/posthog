import React, { useEffect } from 'react'
import { Drawer as AntDrawer } from 'antd'

export function Drawer(props: Record<string, any>): JSX.Element {
    /* Extends Ant's Drawer component to add a class to the HTML body knowing when a drawer is open,
    used to alter global stylying (e.g. move Papercups widget) */
    const { visible } = props

    useEffect(() => {
        if (visible) {
            document.body.classList.add('drawer-open')
        } else {
            document.body.classList.remove('drawer-open')
        }
    }, [visible])

    return <AntDrawer {...props} />
}
