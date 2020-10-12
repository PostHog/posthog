import React, { KeyboardEvent, useCallback, useMemo } from 'react'
import { SearchOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { commandLogic } from './commandLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import squeakFile from './../../../../public/squeak.mp3'
import PostHogIcon from './../../../../public/icon-white.svg'

export function CommandInput(): JSX.Element {
    const { searchInput, isSqueak } = useValues(commandLogic)
    const { setSearchInput, hidePalette } = useActions(commandLogic)

    const squeakAudio: HTMLAudioElement | null = useMemo(
        () => squeakAudio || (isSqueak ? new Audio(squeakFile) : null),
        [isSqueak]
    )

    const handleKeyDown = useCallback(
        (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                event.preventDefault()
                if (searchInput) setSearchInput('')
                // At first, only erase input
                else hidePalette() // Then hide palette
            } else if (event.key === 'k' && (event.ctrlKey || event.metaKey)) hidePalette()
        },
        [searchInput, hidePalette]
    )

    const handleEnterDown = useCallback(
        (event: KeyboardEvent<HTMLInputElement>) => {
            if (isSqueak && event.key === 'Enter') {
                squeakAudio?.play()
            }
        },
        [isSqueak, squeakAudio]
    )

    useEventListener('keydown', handleEnterDown)

    return (
        <div className="palette__row">
            {isSqueak ? (
                <img src={PostHogIcon} className="palette__icon"></img>
            ) : (
                <SearchOutlined className="palette__icon" />
            )}
            <input
                className="palette__display palette__input"
                autoFocus
                value={searchInput}
                onKeyDown={handleKeyDown}
                onChange={(event) => {
                    setSearchInput(event.target.value)
                }}
                placeholder="What would you like to do? Try some suggestions…"
            />
        </div>
    )
}
