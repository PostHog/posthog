import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { themeLogic } from 'lib/logic/themeLogic'
import { inStorybook } from 'lib/utils/dom'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { useShortcut } from '../Shortcuts/useShortcut'
import { hedgehogModeLogic } from './hedgehogModeLogic'
import { HedgehogModeConfig } from './types'

export const HedgeHogModeRenderer =
    typeof window !== 'undefined'
        ? lazyWithRetry(() =>
              import('@posthog/hedgehog-mode').then((module) => ({ default: module.HedgehogModeRenderer }))
          )
        : () => null

export const getHedgehogModeAssetsUrl = (): string => {
    let path = `/static/hedgehog-mode`
    const toolbarAPIUrl = toolbarConfigLogic.findMounted()?.values.uiHost

    if (inStorybook()) {
        // Nothing to do
    } else if (toolbarAPIUrl) {
        path = `${toolbarAPIUrl}${path}`
    } else if (window.location.hostname !== 'localhost') {
        path = `${window.location.origin}${path}`
    }

    return path
}

export type HedgehogModeProps = {
    enabledOverride?: boolean
}

export function HedgehogMode({ enabledOverride }: HedgehogModeProps): JSX.Element | null {
    const { hedgehogModeEnabled, hedgehogConfig } = useValues(hedgehogModeLogic)
    const { setHedgehogMode, setHedgehogModeEnabled, toggleHedgehogMode } = useActions(hedgehogModeLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const enabled = enabledOverride ?? hedgehogModeEnabled

    const config: HedgehogModeConfig = {
        assetsUrl: getHedgehogModeAssetsUrl(),
        // Seed the actor so it spawns with the user's options (e.g. ai_enabled / "free to roam")
        // already applied, instead of defaulting to roaming until the first syncGame corrects it.
        state: { options: hedgehogConfig.actor_options },
        platforms: {
            selector:
                '.border, .border-t, .LemonButton--primary, .LemonButton--secondary:not(.LemonButton--status-alt:not(.LemonButton--active)), .LemonInput, .LemonSelect, .LemonTable, .LemonSwitch--bordered, .LemonBanner',
            viewportPadding: {
                top: 100,
            },
        },
        onQuit: (game) => {
            game.getAllHedgehogs().forEach((hedgehog) => {
                hedgehog.updateSprite('wave', {
                    reset: true,
                    loop: false,
                })
            })

            setTimeout(() => {
                setHedgehogModeEnabled(false)
            }, 1000)
        },
    }

    useShortcut({
        name: 'ToggleHedgehogMode',
        keybind: [],
        intent: 'Toggle hedgehog mode',
        interaction: 'function',
        callback: toggleHedgehogMode,
    })

    return typeof window !== 'undefined' && enabled ? (
        <Suspense fallback={<span>Loading...</span>}>
            <HedgeHogModeRenderer
                config={config}
                onGameReady={(game) => setHedgehogMode(game)}
                style={{
                    position: 'fixed',
                    zIndex: 999998,
                }}
                theme={isDarkModeOn ? 'dark' : 'light'}
            />
        </Suspense>
    ) : null
}
