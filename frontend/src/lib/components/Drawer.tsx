import React, { PropsWithChildren } from 'react'
import { Drawer as AntDrawer } from 'antd'
import { DrawerProps } from 'antd/lib/drawer'
import { styles } from '~/styles/vars'

export function Drawer(props: PropsWithChildren<DrawerProps>): JSX.Element {
    return <AntDrawer {...props} zIndex={styles.zDrawer} />
}
