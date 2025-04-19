import type { HedgehogModeConfig } from '@posthog/hedgehog-mode'
import { useActions, useValues } from 'kea'
import { lazy, Suspense } from 'react'

import { hedgehogModeLogic } from './hedgehogModeLogic'

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

    return typeof window !== 'undefined' && hedgehogModeEnabled ? (
        <Suspense fallback={<span>Loading...</span>}>
            <HedgeHogModeRenderer
                config={config}
                onGameReady={(game) => {
                    setHedgehogMode(game)
                    console.log('Hedgehog mode ready')
                }}
                style={{
                    position: 'fixed',
                    zIndex: 999998,
                }}
            />
        </Suspense>
    ) : null
}
