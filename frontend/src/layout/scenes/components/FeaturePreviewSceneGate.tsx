import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { ConceptWaitlistCTA } from 'lib/components/FeaturePreviews/ConceptWaitlistCTA'
import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
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

import { featurePreviewGateSettlingLogic } from './featurePreviewGateSettlingLogic'
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
    const settlingLogic = featurePreviewGateSettlingLogic({ flag: config.flag })
    const { settling } = useValues(settlingLogic)
    const { markServerCaughtUp } = useActions(settlingLogic)

    const isEnabled = featureFlags[config.flag as keyof typeof featureFlags]
    if (isEnabled && !settling) {
        return <>{children}</>
    }
    // Only hold the enabling state once the flag is actually on locally; before that the gate
    // has nothing to wait for and should keep showing the toggle.
    const justEnrolled = settling && !!isEnabled
    return (
        <>
            {config.productIntent && settling && (
                <SetupDetectionEarlyStop productKey={config.productIntent} onServerCaughtUp={markServerCaughtUp} />
            )}
            <FeaturePreviewGateContent config={config} justEnrolled={justEnrolled} />
        </>
    )
}

/**
 * Watches the product's own setup detection while the gate settles: once detection has any real
 * answer from the server, the enrollment window has closed and the wait has done its job. Lives
 * in its own component so `productSetupStatusLogic` is only mounted with a real productKey -
 * the keyed logic throws on a missing key, and gates without a product intent simply wait out
 * the timer.
 */
function SetupDetectionEarlyStop({
    productKey,
    onServerCaughtUp,
}: {
    productKey: ProductKey
    onServerCaughtUp: () => void
}): null {
    const { status: setupStatus } = useValues(productSetupStatusLogic({ productKey }))
    useEffect(() => {
        if (setupStatus !== 'loading' && setupStatus !== 'unknown') {
            onServerCaughtUp()
        }
    }, [setupStatus, onServerCaughtUp])
    return null
}

function FeaturePreviewGateContent({
    config,
    justEnrolled,
}: {
    config: FeaturePreviewGateConfig
    justEnrolled: boolean
}): JSX.Element {
    const { earlyAccessFeatures } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures, updateEarlyAccessFeatureEnrollment, addProductIntentForCrossSell } =
        useActions(featurePreviewsLogic)
    const { startSettling } = useActions(featurePreviewGateSettlingLogic({ flag: config.flag }))
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

    // The user just opted in: the flag is on locally but the API still 403s until ingestion
    // catches up. Hold here instead of mounting a scene whose every request fails.
    if (justEnrolled) {
        return (
            <SceneContent>
                {sceneConfig?.name && (
                    <SceneTitleSection
                        name={sceneConfig.name}
                        description={sceneConfig.description}
                        resourceType={{ type: sceneConfig.iconType || 'default' }}
                    />
                )}
                <div
                    className="flex items-center gap-2 text-secondary"
                    data-attr="feature-preview-enabling"
                    role="status"
                >
                    <Spinner className="text-lg" />
                    <span>Turning the feature preview on. This takes a few seconds.</span>
                </div>
            </SceneContent>
        )
    }

    // Concept ("Coming Soon") features never enable their flag, so the enrollment toggle is a
    // dead end there. When the feature carries a waitlist survey, collect an email instead.
    // Alpha and beta enrollments do enable their flag, so those stages keep the self-serve
    // toggle even when a legacy waitlist survey id is still attached to the payload.
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
                                onChange={(checked) => {
                                    updateEarlyAccessFeatureEnrollment(feature.flagKey, checked, feature.stage)
                                    // featurePreviewsLogic refuses enrollment for impersonated
                                    // sessions, so there is nothing to wait on in that case.
                                    if (checked && !window.IMPERSONATED_SESSION) {
                                        startSettling()
                                    }
                                }}
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
