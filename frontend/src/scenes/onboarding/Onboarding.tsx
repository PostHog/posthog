import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { useEffect } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: Onboarding,
    // logic: featureFlagsLogic,
}

export function Onboarding(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    useEffect(() => {
        if (featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] !== 'test') {
            location.href = urls.ingestion()
        }
    }, [])

    return (
        <div className="flex flex-col w-full h-full p-6 items-center justify-center bg-mid">
            <div className="mb-8">
                <h1 className="text-center text-4xl">Product analytics</h1>
                <p className="text-center">
                    Pick your first product to get started with. You can set up any others you'd like later.
                </p>
            </div>

            <div className="flex w-full max-w-xl justify-center gap-6 flex-wrap" />
        </div>
    )
}
