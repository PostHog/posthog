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

    // Surface saved passkeys in the email field's autofill menu as soon as the form renders, so a
    // user with a passkey signs in with one tap and no modal — the WebKit-safe replacement for the
    // old auto-triggered prompt. Runs once on mount; no-ops where autofill isn't supported.
    useEffect(() => {
        startConditionalPasskeyLogin()
    }, [startConditionalPasskeyLogin])

    return <VariantLogin />
}
