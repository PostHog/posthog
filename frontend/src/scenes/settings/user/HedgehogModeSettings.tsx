import { useActions, useValues } from 'kea'
import { Suspense, lazy, useEffect, useState } from 'react'

import { LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { getHedgehogModeAssetsUrl } from 'lib/components/HedgehogMode/HedgehogMode'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'

const LazyHedgehogCustomization =
    typeof window !== 'undefined'
        ? lazy(() => import('@posthog/hedgehog-mode').then((module) => ({ default: module.HedgehogCustomization })))
        : () => null

const LazyHedgehogModeRendererContent =
    typeof window !== 'undefined'
        ? lazy(() =>
              import('@posthog/hedgehog-mode').then((module) => ({ default: module.HedgehogModeRendererContent }))
          )
        : () => null

let HedgeHogModeClass: any = null

const getHedgeHogMode = async (): Promise<any> => {
    if (!HedgeHogModeClass && typeof window !== 'undefined') {
        const module = await import('@posthog/hedgehog-mode')
        HedgeHogModeClass = module.HedgeHogMode
    }
    return HedgeHogModeClass
}

export function HedgehogModeSettings(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { updateRemoteConfig } = useActions(hedgehogModeLogic)

    if (typeof window === 'undefined') {
        return <LemonSkeleton />
    }

    return (
        <>
            <div className="flex gap-2">
                <LemonSwitch
                    label="Enable hedgehog mode"
                    data-attr="hedgehog-mode-switch"
                    onChange={(checked) => updateRemoteConfig({ enabled: checked })}
                    checked={hedgehogConfig.enabled}
                    bordered
                />
                <LemonSwitch
                    label="Use as profile picture"
                    data-attr="hedgehog-profile-picture"
                    onChange={(checked) => updateRemoteConfig({ use_as_profile: checked })}
                    checked={hedgehogConfig.use_as_profile}
                    bordered
                />
            </div>

            <div className="border rounded mt-2 bg-surface-primary p-3">
                <Suspense fallback={<LemonSkeleton className="w-full h-64" />}>
                    <LazyHedgehogModeRendererContent id="hedgehog-customization">
                        <HedgehogCustomizationWrapper
                            config={hedgehogConfig.actor_options}
                            setConfig={(config) => updateRemoteConfig({ actor_options: config })}
                        />
                    </LazyHedgehogModeRendererContent>
                </Suspense>
            </div>
        </>
    )
}

function HedgehogCustomizationWrapper({
    config,
    setConfig,
}: {
    config: any
    setConfig: (config: any) => void
}): JSX.Element {
    const [game, setGame] = useState<any>(null)

    useEffect(() => {
        void getHedgeHogMode().then((HedgeHogModeClass) => {
            if (HedgeHogModeClass) {
                setGame(
                    new HedgeHogModeClass({
                        assetsUrl: getHedgehogModeAssetsUrl(),
                    })
                )
            }
        })
    }, [])

    if (!game) {
        return <LemonSkeleton className="w-full h-64" />
    }

    return (
        <Suspense fallback={<LemonSkeleton className="w-full h-64" />}>
            <LazyHedgehogCustomization config={config} setConfig={setConfig} game={game} />
        </Suspense>
    )
}
