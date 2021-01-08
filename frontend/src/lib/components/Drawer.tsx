import React, { PropsWithChildren, useEffect } from 'react'
import { Drawer as AntDrawer } from 'antd'
import { DrawerProps } from 'antd/lib/drawer'

/**
 * Ant Drawer extended to add class 'drawer-open' to <body> when drawer is out. Used to alter Papercups widget position.
 */
export function Drawer(props: PropsWithChildren<DrawerProps>): JSX.Element {
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
