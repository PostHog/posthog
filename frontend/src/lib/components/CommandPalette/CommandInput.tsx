import React from 'react'
import { SearchOutlined, EditOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { commandPaletteLogic } from './commandPaletteLogic'
import PostHogIcon from './../../../../public/icon-white.svg'

export function CommandInput(): JSX.Element {
    const { input, isSqueak, activeFlow } = useValues(commandPaletteLogic)
    const { setInput } = useActions(commandPaletteLogic)

    return (
        <div className="palette__row">
            {isSqueak ? (
                <img src={PostHogIcon} className="palette__icon"></img>
            ) : activeFlow ? (
                activeFlow.icon ?? <EditOutlined className="palette__icon" />
            ) : (
                <SearchOutlined className="palette__icon" />
            )}
            <input
                className="palette__display palette__input"
                autoFocus
                value={input}
                onChange={(event) => {
                    setInput(event.target.value)
                }}
                placeholder={activeFlow?.instruction ?? 'What would you like to do? Try some suggestions…'}
            />
        </div>
    )
}
