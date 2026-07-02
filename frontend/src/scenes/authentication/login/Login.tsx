import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { passkeyLogic } from 'scenes/authentication/shared/passkeyLogic'
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
    const { startConditionalPasskeyLogin } = useActions(passkeyLogic)
    const { Login: VariantLogin } = authFlowVariantRegistry[resolveAuthFlowVariant(featureFlags)]

    // WebKit (Safari/iOS) can't open the passkey modal without a user gesture, so we show
    // passkeys via the email field's autofill instead. Other browsers keep the auto-modal.
    useEffect(() => {
        startConditionalPasskeyLogin()
    }, [startConditionalPasskeyLogin])

    return <VariantLogin />
}
