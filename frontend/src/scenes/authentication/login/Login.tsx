import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { authFlowVariantRegistry } from '../authFlowVariantRegistry'
import { resolveAuthFlowVariant } from '../authFlowVariants'
import { loginLogic } from './loginLogic'

export const scene: SceneExport = {
    component: Login,
    logic: loginLogic,
}

export function Login(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { Login: VariantLogin } = authFlowVariantRegistry[resolveAuthFlowVariant(featureFlags)]
    return <VariantLogin />
}
