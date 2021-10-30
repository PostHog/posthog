import React, { PropsWithChildren } from 'react'
import { Drawer as _Drawer } from 'antd'
import { DrawerProps } from 'antd/lib/drawer'
import { styles } from '../../vars'

export function Drawer(props: PropsWithChildren<DrawerProps>): JSX.Element {
    return <_Drawer {...props} zIndex={styles.zDrawer} />
}
