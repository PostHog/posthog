import React from 'react'
import { LatestVersion } from './LatestVersion'
import { User } from './User'
import { CommandPaletteButton } from './CommandPaletteButton'
import { isMobile } from 'lib/utils'
import './index.scss'

export function TopContent(): JSX.Element {
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
                {!isMobile() && <CommandPaletteButton />}
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
                <User />
            </div>
        </div>
    )
}
