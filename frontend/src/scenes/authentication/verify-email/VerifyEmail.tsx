import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { authFlowVariantRegistry } from '../authFlowVariantRegistry'
import { resolveAuthFlowVariant } from '../authFlowVariants'
import { verifyEmailLogic } from './verifyEmailLogic'

export const scene: SceneExport = {
    component: VerifyEmail,
    logic: verifyEmailLogic,
}

export function VerifyEmail(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { VerifyEmail: VariantVerifyEmail } = authFlowVariantRegistry[resolveAuthFlowVariant(featureFlags)]
    return <VariantVerifyEmail />
}
