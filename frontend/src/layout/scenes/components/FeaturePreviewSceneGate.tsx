import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { featurePreviewsLogic } from '~/layout/FeaturePreviews/featurePreviewsLogic'
import { FeaturePreviewGateConfig } from '~/types'

import { SceneContent } from './SceneContent'
import { SceneTitleSection } from './SceneTitleSection'

export function FeaturePreviewSceneGate({
    config,
    children,
}: {
    config: FeaturePreviewGateConfig
    children: React.ReactNode
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isEnabled = featureFlags[config.flag as keyof typeof featureFlags]
    if (isEnabled) {
        return <>{children}</>
    }
    return <FeaturePreviewGateContent config={config} />
}

function FeaturePreviewGateContent({ config }: { config: FeaturePreviewGateConfig }): JSX.Element {
    const { earlyAccessFeatures } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)
    const { activeSceneId } = useValues(sceneLogic)

    useEffect(() => {
        loadEarlyAccessFeatures()
    }, [loadEarlyAccessFeatures])

    const feature = earlyAccessFeatures.find((f) => f.flagKey === config.flag)
    const sceneConfig = activeSceneId ? sceneConfigurations[activeSceneId] : undefined

    return (
        <SceneContent>
            {sceneConfig?.name && (
                <SceneTitleSection
                    name={sceneConfig.name}
                    description={sceneConfig.description}
                    resourceType={{ type: sceneConfig.iconType || 'default' }}
                />
            )}
            <ProductIntroduction
                productName={config.title}
                thingName="feature"
                titleOverride={config.title}
                description={config.description}
                isEmpty
                actionElementOverride={
                    feature ? (
                        <label className="flex items-center gap-2 cursor-pointer" htmlFor="feature-preview-gate-switch">
                            <LemonSwitch
                                checked={feature.enabled}
                                onChange={(checked) =>
                                    updateEarlyAccessFeatureEnrollment(feature.flagKey, checked, feature.stage)
                                }
                                id="feature-preview-gate-switch"
                            />
                            <span className="font-semibold">Enable feature preview</span>
                        </label>
                    ) : (
                        <LemonButton type="primary" to={urls.settings('user-feature-previews')}>
                            Open feature previews
                        </LemonButton>
                    )
                }
                docsURL={config.docsURL}
            />
        </SceneContent>
    )
}
