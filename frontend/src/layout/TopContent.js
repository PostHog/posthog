import './TopContent.scss'

import React from 'react'
import { LatestVersion } from '~/layout/LatestVersion'
import { User } from '~/layout/User'
import { WorkerStats } from '~/layout/WorkerStats'
import { useActions, useValues } from 'kea'
import { commandLogic } from 'lib/components/CommandPalette/commandLogic'
import { SearchOutlined } from '@ant-design/icons'

export function CommandPaletteButton() {
    const { isPaletteShown } = useValues(commandLogic)
    const { togglePalette } = useActions(commandLogic)

    return (
        <span
            data-attr="command-palette-toggle"
            className="btn btn-sm btn-light"
            onClick={togglePalette}
            title={isPaletteShown ? 'Hide Command Palette' : 'Show Command Palette'}
        >
            <SearchOutlined size="small" /> Cmd + K
        </span>
    )
}

export function TopContent() {
    return (
        <div className="content py-3 layout-top-content">
            <div
                className="layout-top-content"
                style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'center',
                    alignItems: 'center',
                    fontSize: 13,
                }}
            >
                <CommandPaletteButton />
            </div>
            <div
                className="layout-top-content"
                style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'center',
                    alignItems: 'center',
                    fontSize: 13,
                }}
            >
                <LatestVersion />
                <WorkerStats />
                <User />
            </div>
        </div>
    )
}
