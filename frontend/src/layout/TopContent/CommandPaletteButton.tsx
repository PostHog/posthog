import React from 'react'
import { useActions, useValues } from 'kea'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { SearchOutlined } from '@ant-design/icons'
import { platformCommandControlKey } from 'lib/utils'

export function CommandPaletteButton(): JSX.Element {
    const { isPaletteShown } = useValues(commandPaletteLogic)
    const { showPalette } = useActions(commandPaletteLogic)

    return (
        <span
            data-attr="command-palette-toggle"
            className="btn btn-sm btn-light hide-when-small"
            onClick={showPalette}
            title={isPaletteShown ? 'Hide Command Palette' : 'Show Command Palette'}
        >
            <SearchOutlined size={1} style={{ marginRight: '0.5rem' }} />
            {platformCommandControlKey('K')}
        </span>
    )
}
