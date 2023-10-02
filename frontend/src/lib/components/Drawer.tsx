import { PropsWithChildren } from 'react'
import { Drawer as AntDrawer } from 'antd'
import { DrawerProps } from 'antd/lib/drawer'

export function Drawer(props: PropsWithChildren<DrawerProps>): JSX.Element {
    return <AntDrawer {...props} zIndex={950} />
}
