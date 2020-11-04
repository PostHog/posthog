import React from 'react'
import { SearchOutlined, EditOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { commandPaletteLogic } from './commandPaletteLogic'
import PostHogIcon from 'public/icon-white.svg'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'

export function CommandInput(): JSX.Element {
    const { input, isSqueak, activeFlow } = useValues(commandPaletteLogic)
    const { setInput } = useActions(commandPaletteLogic)

    return (
        <div className="palette__row">
            {isSqueak ? (
                <img src={PostHogIcon} className="palette__icon" />
            ) : activeFlow ? (
                <activeFlow.icon className="palette__icon" /> ?? <EditOutlined className="palette__icon" />
            ) : (
                <SearchOutlined className="palette__icon" />
            )}
            <input
                className={`palette__display palette__input ${rrwebBlockClass}`}
                autoFocus
                value={input}
                onChange={(event) => {
                    setInput(event.target.value)
                }}
                placeholder={activeFlow?.instruction ?? 'What would you like to do? Try some suggestions…'}
                data-attr="command-palette-input"
            />
        </div>
    )
}
