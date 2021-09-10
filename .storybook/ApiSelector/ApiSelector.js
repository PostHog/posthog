import React, { useState, memo } from 'react'
import { Icons, IconButton, WithTooltipPure } from '@storybook/components'
import { useGlobals } from '@storybook/api'
import { defaultConnection, GLOBAL_KEY, history, LOCALSTORAGE_HISTORY_KEY, LOCALSTORAGE_KEY } from './constants'
import { ApiForm } from './ApiForm'

export const ApiSelector = memo(() => {
    const [globals, updateGlobals] = useGlobals()
    const selectedConnection =
        globals[GLOBAL_KEY] || JSON.parse(window.localStorage.getItem(LOCALSTORAGE_KEY) || 'false') || defaultConnection
    const [tooltipShown, setTooltipShown] = useState(false)

    const saveApi = (apiHost, apiKey) => {
        let localHistory = JSON.parse(window.localStorage.getItem(LOCALSTORAGE_HISTORY_KEY) || '[]')
        if (![...history, ...localHistory].find((h) => h.apiHost === apiHost && h.apiKey === apiKey)) {
            localHistory = [{ apiHost, apiKey }, ...localHistory]
            window.localStorage.setItem(LOCALSTORAGE_HISTORY_KEY, JSON.stringify(localHistory))
        }
        window.localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify({ apiHost, apiKey }))
        updateGlobals({
            [GLOBAL_KEY]: {
                apiHost,
                apiKey,
            },
        })
        setTooltipShown(false)
    }

    return (
        <WithTooltipPure
            tooltipShown={tooltipShown}
            placement="bottom"
            tooltip={<ApiForm saveApi={saveApi} selectedConnection={selectedConnection} />}
        >
            <IconButton
                key={GLOBAL_KEY}
                title="Choose API connection"
                style={!selectedConnection?.apiHost ? { color: 'red' } : {}}
                onClick={() => setTooltipShown(!tooltipShown)}
            >
                <Icons icon="globe" style={{ marginRight: 5 }} />
                {!selectedConnection?.apiHost ? 'offline' : selectedConnection?.apiHost}
            </IconButton>
        </WithTooltipPure>
    )
})
