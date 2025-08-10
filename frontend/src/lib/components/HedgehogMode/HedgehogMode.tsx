import type { HedgehogModeConfig } from '@posthog/hedgehog-mode'
import { useActions, useValues } from 'kea'
import { lazy, Suspense, useEffect } from 'react'

import { hedgehogModeLogic } from './hedgehogModeLogic'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const HedgeHogModeRenderer =
    typeof window !== 'undefined'
        ? lazy(() => import('@posthog/hedgehog-mode').then((module) => ({ default: module.HedgehogModeRenderer })))
        : () => null

const config: HedgehogModeConfig = {
    assetsUrl: '/static/hedgehog-mode/',
    platformSelector:
        '.border, .border-t, .LemonButton--primary, .LemonButton--secondary:not(.LemonButton--status-alt:not(.LemonButton--active)), .LemonInput, .LemonSelect, .LemonTable, .LemonSwitch--bordered, .LemonBanner',
}

export function HedgehogMode(): JSX.Element | null {
    const { hedgehogModeEnabled } = useValues(hedgehogModeLogic)
    const { setHedgehogMode } = useActions(hedgehogModeLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return typeof window !== 'undefined' && hedgehogModeEnabled ? (
        <Suspense fallback={<span>Loading...</span>}>
            <HedgeHogModeRenderer
                config={config}
                onGameReady={(game) => {
                    setHedgehogMode(game)
                }}
                style={{
                    position: 'fixed',
                    zIndex: 999998,
                }}
                theme={isDarkModeOn ? 'dark' : 'light'}
            />
        </Suspense>
    ) : null
}
