import type { HedgehogModeConfig } from '@posthog/hedgehog-mode'
import { useActions, useValues } from 'kea'
import { lazy, Suspense } from 'react'

import { hedgehogModeLogic } from './hedgehogModeLogic'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { inStorybook } from 'lib/utils'

export const HedgeHogModeRenderer =
    typeof window !== 'undefined'
        ? lazy(() => import('@posthog/hedgehog-mode').then((module) => ({ default: module.HedgehogModeRenderer })))
        : () => null

const getAssetsUrl = (): string => {
    let path = `/static/hedgehog-mode/`
    const toolbarAPIUrl = toolbarConfigLogic.findMounted()?.values.apiURL

    if (inStorybook()) {
        // Nothing to do
    } else if (window.location.hostname !== 'localhost') {
        path = `https://us.posthog.com${path}`
    } else if (toolbarAPIUrl) {
        path = `${toolbarAPIUrl}${path}`
    }

    return path
}

export type HedgehogModeProps = {
    enabledOverride?: boolean
}

// TODO: Ensure only one gets rendered at a time

export function HedgehogMode({ enabledOverride }: HedgehogModeProps): JSX.Element | null {
    const { hedgehogModeEnabled } = useValues(hedgehogModeLogic)
    const { setHedgehogMode } = useActions(hedgehogModeLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const enabled = enabledOverride ?? hedgehogModeEnabled

    const config: HedgehogModeConfig = {
        assetsUrl: getAssetsUrl(),
        platformSelector:
            '.border, .border-t, .LemonButton--primary, .LemonButton--secondary:not(.LemonButton--status-alt:not(.LemonButton--active)), .LemonInput, .LemonSelect, .LemonTable, .LemonSwitch--bordered, .LemonBanner',
    }

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
