import React from 'react'
import './Navigation.scss'
import { BarsOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'

export function TopNavigation(): JSX.Element {
    const { setMenuCollapsed } = useActions(navigationLogic)
    const { menuCollapsed } = useValues(navigationLogic)

    return (
        <div className="navigation-top">
            <div>
                <div className="hide-gte-lg cursor-pointer" onClick={() => setMenuCollapsed(!menuCollapsed)}>
                    <BarsOutlined />
                </div>
            </div>
            <div className="middle">Project chooser</div>
            <div>Left</div>
        </div>
    )
}
