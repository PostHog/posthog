import type { HedgehogModeConfig } from '@posthog/hedgehog-mode'
import { lazy, Suspense } from 'react'

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
    // const {} = useActions(hedgehogModeLogic)

    return typeof window !== 'undefined' && true ? (
        <Suspense fallback={<span>Loading...</span>}>
            <HedgeHogModeRenderer
                config={config}
                onGameReady={() => {
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
