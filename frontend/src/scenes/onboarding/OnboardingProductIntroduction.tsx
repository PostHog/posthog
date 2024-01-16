import { SceneExport } from 'scenes/sceneTypes'

import { onboardingLogic } from './onboardingLogic'

export const scene: SceneExport = {
    component: OnboardingProductIntroduction,
    logic: onboardingLogic,
}

export function OnboardingProductIntroduction(): JSX.Element | null {
    return <p>haiiiii</p>
}
