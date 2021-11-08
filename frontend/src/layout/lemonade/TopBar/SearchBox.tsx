import { useActions } from 'kea'
import React from 'react'
import { commandPaletteLogic } from '../../../lib/components/CommandPalette/commandPaletteLogic'
import { platformCommandControlKey } from '../../../lib/utils'
import { SearchOutlined } from '@ant-design/icons'

export function SearchBox(): JSX.Element {
    const { showPalette } = useActions(commandPaletteLogic)

    return (
        <div className="SearchBox" onClick={showPalette} data-attr="command-palette-toggle">
            <div className="SearchBox__primary-area">
                <SearchOutlined className="SearchBox__magnifier" />
                Search
            </div>
            <div className="SearchBox__keyboard-shortcut">{platformCommandControlKey('K')}</div>
        </div>
    )
}
