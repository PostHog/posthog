import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { SSOProvider } from '~/types'

/** A provider that the instance has configured, and that the viewer's feature flags do not yet allow. */
export function isSocialProviderHeldBack(provider: SSOProvider | string, featureFlags: FeatureFlagsSet): boolean {
    return provider === 'chatgpt' && !featureFlags[FEATURE_FLAGS.SIGN_IN_WITH_CHATGPT]
}
