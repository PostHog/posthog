import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { ConceptWaitlistCTA } from 'lib/components/FeaturePreviews/ConceptWaitlistCTA'
import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { supportLogic } from 'lib/components/Support/supportLogic'
import {
    FEATURE_PREVIEW_SELF_HOSTED_DISABLED_REASON,
    areClientFeatureFlagsHonored,
    featureFlagLogic,
} from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
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
    const { loadEarlyAccessFeatures, updateEarlyAccessFeatureEnrollment, addProductIntentForCrossSell } =
        useActions(featurePreviewsLogic)
    const { activeSceneId } = useValues(sceneLogic)
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    useEffect(() => {
        loadEarlyAccessFeatures()
    }, [loadEarlyAccessFeatures])

    const feature = earlyAccessFeatures.find((f) => f.flagKey === config.flag)
    const sceneIdForHeader = config.sceneId ?? activeSceneId
    const sceneConfig = sceneIdForHeader ? sceneConfigurations[sceneIdForHeader] : undefined
    const flagsHonored = areClientFeatureFlagsHonored(preflight)

    // Concept ("Coming Soon") features never enable their flag, so the enrollment toggle is a
    // dead end there. When the feature carries a waitlist survey, collect an email instead.
    if (feature?.stage === 'concept' && feature.payload?.survey_id) {
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
                    thingName="feature"
                    titleOverride={config.title}
                    description={config.description}
                    isEmpty
                    actionElementOverride={
                        <ConceptWaitlistCTA
                            feature={feature}
                            size="medium"
                            onSignUp={() => {
                                if (config.productIntent) {
                                    void addProductIntentForCrossSell({
                                        from: ProductKey.EARLY_ACCESS_FEATURES,
                                        to: config.productIntent,
                                        intent_context: ProductIntentContext.FEATURE_PREVIEW_ENABLED,
                                    })
                                }
                            }}
                        />
                    }
                    docsURL={config.docsURL}
                />
            </SceneContent>
        )
    }

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
                thingName="feature"
                titleOverride={config.title}
                description={config.description}
                isEmpty
                actionElementOverride={
                    feature ? (
                        <label
                            className={`flex items-center gap-2 ${flagsHonored ? 'cursor-pointer' : 'cursor-default'}`}
                            htmlFor="feature-preview-gate-switch"
                        >
                            <LemonSwitch
                                checked={feature.enabled}
                                disabledReason={!flagsHonored && FEATURE_PREVIEW_SELF_HOSTED_DISABLED_REASON}
                                onChange={(checked) =>
                                    updateEarlyAccessFeatureEnrollment(feature.flagKey, checked, feature.stage)
                                }
                                id="feature-preview-gate-switch"
                            />
                            <span className="font-semibold">Enable feature preview</span>
                        </label>
                    ) : (
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center gap-2">
                                <LemonButton type="primary" to={urls.featurePreview(config.flag)}>
                                    Open feature previews
                                </LemonButton>
                                {config.offerRequestAccess && preflight?.cloud && (
                                    <LemonButton
                                        type="secondary"
                                        onClick={() =>
                                            openSupportForm({
                                                kind: 'support',
                                                message: `I'd like to request access to ${config.title}.`,
                                            })
                                        }
                                    >
                                        Request access
                                    </LemonButton>
                                )}
                            </div>
                            {!flagsHonored && (
                                <span className="text-secondary text-xs">
                                    On self-hosted instances, feature previews are controlled by the
                                    PERSISTED_FEATURE_FLAGS environment variable.
                                </span>
                            )}
                        </div>
                    )
                }
                docsURL={config.docsURL}
            />
        </SceneContent>
    )
}
