import React from 'react'
import { useActions, useValues } from 'kea'
import { commandLogic } from 'lib/components/CommandPalette/commandLogic'
import { SearchOutlined } from '@ant-design/icons'
import { platformSuperKey } from 'lib/utils'

export function CommandPaletteButton(): JSX.Element {
    const { isPaletteShown } = useValues(commandLogic)
    const { showPalette } = useActions(commandLogic)

    return (
        <span
            data-attr="command-palette-toggle"
            className="btn btn-sm btn-light"
            onClick={() => {
                showPalette()
            }}
            title={isPaletteShown ? 'Hide Command Palette' : 'Show Command Palette'}
        >
            <SearchOutlined size={1} style={{ marginRight: '0.5rem' }} />
            {platformSuperKey()} + K
        </span>
    )
}
