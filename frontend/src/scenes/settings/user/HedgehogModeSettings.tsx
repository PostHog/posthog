import { useActions, useValues } from 'kea'
import { CSSProperties, Suspense, useEffect, useState } from 'react'

import { LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill'

import { getHedgehogModeAssetsUrl } from 'lib/components/HedgehogMode/HedgehogMode'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

const LazyHedgehogCustomization =
    typeof window !== 'undefined'
        ? lazyWithRetry(() =>
              import('@posthog/hedgehog-mode').then((module) => ({ default: module.HedgehogCustomization }))
          )
        : () => null

const LazyHedgehogModeRendererContent =
    typeof window !== 'undefined'
        ? lazyWithRetry(() =>
              import('@posthog/hedgehog-mode').then((module) => ({ default: module.HedgehogModeRendererContent }))
          )
        : () => null

// The customizer renders in its own shadow root and reads these variables off its host element, so this is the
// only way to put it on quill tokens.
const QUILL_CUSTOMIZATION_THEME = {
    '--font-family': 'var(--font-sans)',
    '--color-text': 'var(--card-foreground)',
    '--color-background': 'var(--card)',
    '--color-border': 'var(--input)',
    '--color-border-light': 'var(--border)',
    '--color-hover': 'var(--fill-hover)',
    '--color-danger': 'var(--destructive-foreground)',
    '--border-radius-sm': 'var(--radius-sm)',
    '--border-radius-md': 'var(--radius-md)',
} as CSSProperties

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleEnabledChange = (checked: boolean): void => updateRemoteConfig({ enabled: checked })

    const handleUseAsProfileChange = (checked: boolean): void => updateRemoteConfig({ use_as_profile: checked })

    const handleActorOptionsChange = (config: any): void => updateRemoteConfig({ actor_options: config })

    if (typeof window === 'undefined') {
        return todayRailNav ? <Skeleton className="h-8" /> : <LemonSkeleton />
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap gap-4">
                    <QuillSettingSwitch
                        label="Enable hedgehog mode"
                        dataAttr="hedgehog-mode-switch"
                        checked={hedgehogConfig.enabled}
                        onCheckedChange={handleEnabledChange}
                    />
                    <QuillSettingSwitch
                        label="Use as profile picture"
                        dataAttr="hedgehog-profile-picture"
                        checked={hedgehogConfig.use_as_profile}
                        onCheckedChange={handleUseAsProfileChange}
                    />
                </div>
                <div className="rounded-lg border border-border bg-card p-3 text-card-foreground">
                    <Suspense fallback={<Skeleton className="w-full h-64" />}>
                        <LazyHedgehogModeRendererContent id="hedgehog-customization" style={QUILL_CUSTOMIZATION_THEME}>
                            <HedgehogCustomizationWrapper
                                config={hedgehogConfig.actor_options}
                                setConfig={handleActorOptionsChange}
                            />
                        </LazyHedgehogModeRendererContent>
                    </Suspense>
                </div>
            </div>
        )
    }

    return (
        <>
            <div className="flex gap-2">
                <LemonSwitch
                    label="Enable hedgehog mode"
                    data-attr="hedgehog-mode-switch"
                    onChange={handleEnabledChange}
                    checked={hedgehogConfig.enabled}
                    bordered
                />
                <LemonSwitch
                    label="Use as profile picture"
                    data-attr="hedgehog-profile-picture"
                    onChange={handleUseAsProfileChange}
                    checked={hedgehogConfig.use_as_profile}
                    bordered
                />
            </div>

            <div className="border rounded mt-2 bg-surface-primary p-3">
                <Suspense fallback={<LemonSkeleton className="w-full h-64" />}>
                    <LazyHedgehogModeRendererContent id="hedgehog-customization">
                        <HedgehogCustomizationWrapper
                            config={hedgehogConfig.actor_options}
                            setConfig={handleActorOptionsChange}
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const loadingSkeleton = todayRailNav ? (
        <Skeleton className="w-full h-64" />
    ) : (
        <LemonSkeleton className="w-full h-64" />
    )

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
        return loadingSkeleton
    }

    return (
        <Suspense fallback={loadingSkeleton}>
            <LazyHedgehogCustomization config={config} setConfig={setConfig} game={game} />
        </Suspense>
    )
}
