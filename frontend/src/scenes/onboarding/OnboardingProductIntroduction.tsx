import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { onboardingLogic } from './onboardingLogic'

export const scene: SceneExport = {
    component: OnboardingProductIntroduction,
    logic: onboardingLogic,
}

export function OnboardingProductIntroduction(): JSX.Element | null {
    const { product, productKey } = useValues(onboardingLogic)
    return product ? (
        <p>
            type {product?.type}
            key {productKey}
        </p>
    ) : (
        <div className="w-full text-center text-3xl mt-12">
            <Spinner />
        </div>
    )
}
