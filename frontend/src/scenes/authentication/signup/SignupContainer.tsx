import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { authFlowVariantRegistry } from '../authFlowVariantRegistry'
import { resolveAuthFlowVariant } from '../authFlowVariants'

export const scene: SceneExport = {
    component: SignupContainer,
}

export function SignupContainer(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { Signup: VariantSignup } = authFlowVariantRegistry[resolveAuthFlowVariant(featureFlags)]
    return <VariantSignup />
}
