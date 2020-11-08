import React from 'react'
import { useActions, useValues } from 'kea'
import { commandPaletteLogic } from 'lib/components/CommandPalette/commandPaletteLogic'
import { SearchOutlined } from '@ant-design/icons'
import { platformCommandControlKey } from 'lib/utils'
import { Button } from 'antd'

export function CommandPaletteButton(): JSX.Element {
    const { isPaletteShown } = useValues(commandPaletteLogic)
    const { showPalette } = useActions(commandPaletteLogic)

    return (
        <Button
            data-attr="command-palette-toggle"
            className="hide-when-small"
            onClick={showPalette}
            title={isPaletteShown ? 'Hide Command Palette' : 'Show Command Palette'}
            icon={<SearchOutlined />}
        >
            {platformCommandControlKey('K')}
        </Button>
    )
}
