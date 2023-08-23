import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { useEffect } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { LemonButton } from '@posthog/lemon-ui'
import { onboardingLogic } from './onboardingLogic'

export const scene: SceneExport = {
    component: Onboarding,
    // logic: featureFlagsLogic,
}

export function Onboarding(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { product } = useValues(onboardingLogic)

    useEffect(() => {
        if (featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] !== 'test') {
            location.href = urls.ingestion()
        }
    }, [])

    return product ? (
        <div className="flex flex-col w-full min-h-full p-6 bg-mid">
            <div className="mb-8">
                <h1 className="text-4xl font-bold">{product.name}</h1>
                <h3 className="font-bold">{product.description}</h3>
                <div className="flex gap-x-2">
                    <LemonButton type="primary">Get started</LemonButton>
                    {product.docs_url && (
                        <LemonButton type="secondary" to={product.docs_url}>
                            Learn more
                        </LemonButton>
                    )}
                </div>
            </div>

            <div className="flex w-full max-w-xl justify-center gap-6 flex-wrap" />
        </div>
    ) : null
}
