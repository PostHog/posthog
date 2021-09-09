import React, { useState, memo } from 'react'
import { Icons, IconButton, WithTooltipPure } from '@storybook/components'
import { useGlobals } from '@storybook/api'
import { defaultConnection, GLOBAL_KEY, history } from './constants'
import { ApiForm } from './ApiForm'

export const ApiSelector = memo(() => {
    const [globals, updateGlobals] = useGlobals()
    const selectedConnection = globals[GLOBAL_KEY] || defaultConnection
    const [tooltipShown, setTooltipShown] = useState(false)

    const saveApi = (apiHost, apiKey) => {
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
