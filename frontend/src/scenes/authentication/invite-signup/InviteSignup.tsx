import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { authFlowVariantRegistry } from '../authFlowVariantRegistry'
import { resolveAuthFlowVariant } from '../authFlowVariants'
import { inviteSignupLogic } from './inviteSignupLogic'

export const scene: SceneExport = {
    component: InviteSignup,
    logic: inviteSignupLogic,
}

export function InviteSignup(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { InviteSignup: VariantInviteSignup } = authFlowVariantRegistry[resolveAuthFlowVariant(featureFlags)]
    return <VariantInviteSignup />
}
